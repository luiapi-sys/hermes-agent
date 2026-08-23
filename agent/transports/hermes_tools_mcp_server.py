"""Hermes-tools-as-MCP server for the codex_app_server runtime.

When the user runs `openai/*` turns through the codex app-server, codex
owns the loop and builds its own tool list. By default, that means
Hermes' richer tool surface is unreachable unless it is bridged through MCP.

This module supports two exposure modes controlled by ``HERMES_MCP_MODE``:

``curated`` (default)
    Preserve the historical Codex-oriented allowlist. Tools that duplicate
    Codex built-ins remain hidden and agent-loop tools stay out of the MCP
    surface.

``full``
    Expose every Hermes tool definition that is currently available from the
    registry. Configured external MCP servers are discovered before the raw
    pre-Tool-Search catalog is snapshotted, so plugin/MCP tools are included as
    well as built-ins. Availability checks still apply. The four agent-loop
    tools (``delegate_task``, ``memory``, ``session_search`` and ``todo``) are
    routed through a dedicated MCP context bridge while still executing through
    ``model_tools.handle_function_call()``.

External MCP discovery is enabled by default in full mode. Set
``HERMES_MCP_DISCOVER_EXTERNAL=0`` to skip it when fast/offline startup is more
important than a complete configured MCP surface.

Run with: python -m agent.transports.hermes_tools_mcp_server
Spawned by: CodexAppServerSession.ensure_started() when the runtime is active
            and config opts in.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

MCP_MODE_ENV = "HERMES_MCP_MODE"
MCP_DISCOVER_EXTERNAL_ENV = "HERMES_MCP_DISCOVER_EXTERNAL"
MCP_MODE_CURATED = "curated"
MCP_MODE_FULL = "full"
_VALID_MCP_MODES = {MCP_MODE_CURATED, MCP_MODE_FULL}

# JSON Schema type -> Python type mapping for signature generation
_JSON_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _signature_from_schema(schema: dict | None) -> tuple[inspect.Signature, dict[str, type]]:
    """Build a Python function signature and annotations from a JSON schema."""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    params, annots = [], {}

    for pname, pspec in props.items():
        if pname.startswith("_"):
            continue
        py = _JSON_TO_PY.get((pspec or {}).get("type"), Any)
        ann, default = (
            (py, inspect.Parameter.empty)
            if pname in required
            else (Optional[py], None)
        )
        annots[pname] = ann
        params.append(
            inspect.Parameter(
                pname, inspect.Parameter.KEYWORD_ONLY, annotation=ann, default=default
            )
        )

    return inspect.Signature(params, return_annotation=str), annots


# Historical Codex-oriented allowlist. Keep this stable for curated mode so
# existing codex_app_server users do not suddenly receive duplicate shell/file
# tools or agent-loop tools.
EXPOSED_TOOLS: tuple[str, ...] = (
    "web_search",
    "web_extract",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_press",
    "browser_snapshot",
    "browser_scroll",
    "browser_back",
    "browser_get_images",
    "browser_console",
    "browser_vision",
    "vision_analyze",
    "image_generate",
    "skill_view",
    "skills_list",
    "text_to_speech",
    "kanban_complete",
    "kanban_block",
    "kanban_comment",
    "kanban_heartbeat",
    "kanban_show",
    "kanban_list",
    "kanban_create",
    "kanban_unblock",
    "kanban_link",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning("invalid %s=%r; using default=%s", name, raw, default)
    return default


def _resolve_mcp_mode(value: str | None = None) -> str:
    """Resolve and validate the MCP exposure mode.

    Invalid values fail closed to curated mode instead of widening the tool
    surface accidentally.
    """
    raw = value if value is not None else os.environ.get(MCP_MODE_ENV, MCP_MODE_CURATED)
    mode = str(raw or MCP_MODE_CURATED).strip().lower()
    if mode not in _VALID_MCP_MODES:
        logger.warning(
            "invalid %s=%r; falling back to %s",
            MCP_MODE_ENV,
            raw,
            MCP_MODE_CURATED,
        )
        return MCP_MODE_CURATED
    return mode


def _resolve_exposed_tool_names(
    all_defs: dict[str, dict],
    *,
    mode: str | None = None,
) -> tuple[str, ...]:
    """Return tool names exposed by the selected MCP mode."""
    resolved_mode = _resolve_mcp_mode(mode)
    if resolved_mode == MCP_MODE_FULL:
        return tuple(sorted(all_defs))
    return EXPOSED_TOOLS


def _discover_external_mcp_tools(mode: str) -> None:
    """Discover configured external MCP tools before the full-mode snapshot.

    Discovery is intentionally synchronous here. Unlike interactive Hermes
    entry points, this server registers a static FastMCP tool surface once at
    startup; a background discovery that finishes later would mutate the Hermes
    registry but would not retroactively add those tools to this MCP server.

    The existing startup helper suppresses interactive OAuth so no prompt can
    write to stdin/stdout, which are the MCP protocol wire in this process.
    """
    if mode != MCP_MODE_FULL:
        return
    if not _env_bool(MCP_DISCOVER_EXTERNAL_ENV, True):
        logger.info("external MCP discovery disabled by %s", MCP_DISCOVER_EXTERNAL_ENV)
        return

    try:
        from hermes_cli.mcp_startup import _discover_mcp_tools_without_interactive_oauth

        _discover_mcp_tools_without_interactive_oauth()
    except Exception as exc:
        # Keep the server usable with built-in/plugin tools when one configured
        # MCP backend is broken. The external discovery layer already applies
        # its own per-server availability/reconnect behavior where possible.
        logger.warning("external MCP discovery failed; continuing with available tools: %s", exc)


def _build_server() -> Any:
    """Create the FastMCP server with Hermes tools attached."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - install hint
        raise ImportError(
            f"hermes-tools MCP server requires the 'mcp' package: {exc}"
        ) from exc

    from model_tools import get_tool_definitions, handle_function_call

    mode = _resolve_mcp_mode()
    mcp = FastMCP(
        "hermes-tools",
        instructions=(
            "Hermes Agent tool surface exposed over MCP. In curated mode this "
            "contains the Codex-safe Hermes-specific subset. In full mode it "
            "contains every currently available built-in, plugin and configured "
            "external MCP registry tool, including delegate_task, memory, "
            "session_search and todo through the MCP agent-context bridge."
        ),
    )

    # model_tools deliberately does not discover configured MCP servers at
    # import time. Full mode is a dedicated MCP process with a static tool list,
    # so discovery must finish before taking the authoritative registry snapshot.
    _discover_external_mcp_tools(mode)

    # Always request the raw pre-Tool-Search catalog. Otherwise progressive
    # disclosure can replace real tools with tool_search/tool_describe/tool_call
    # before this MCP adapter gets a chance to expose them.
    all_defs = {
        td["function"]["name"]: td["function"]
        for td in (
            get_tool_definitions(
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
            or []
        )
        if (
            isinstance(td, dict)
            and td.get("type") == "function"
            and isinstance(td.get("function"), dict)
            and td["function"].get("name")
        )
    }

    tool_names = _resolve_exposed_tool_names(all_defs, mode=mode)

    # Only full mode needs the stateful bridge. Curated mode keeps the exact
    # historical Codex behavior and never initializes memory/session/delegation
    # context as a side effect.
    agent_context_bridge = None
    if mode == MCP_MODE_FULL:
        from agent.transports.hermes_tools_mcp_context import MCPAgentContextBridge

        agent_context_bridge = MCPAgentContextBridge(
            available_tool_names=tuple(sorted(all_defs)),
        )

    exposed_count = 0

    for name in tool_names:
        spec = all_defs.get(name)
        if spec is None:
            logger.debug("skipping %s — not registered in this Hermes process", name)
            continue

        description = spec.get("description") or f"Hermes {name} tool"
        params_schema = spec.get("parameters") or {"type": "object", "properties": {}}

        def _make_handler(
            tool_name: str,
            schema: dict | None,
            tool_description: str,
        ):
            sig, annots = _signature_from_schema(schema)

            def _dispatch(**kwargs: Any) -> str:
                try:
                    # Keep the historical behavior: optional parameters emitted
                    # as Python None are treated as omitted. A future schema-
                    # fidelity change can preserve explicit JSON null separately.
                    args = {k: v for k, v in kwargs.items() if v is not None}
                    if (
                        agent_context_bridge is not None
                        and agent_context_bridge.supports(tool_name)
                    ):
                        return agent_context_bridge.dispatch(tool_name, args or {})
                    return handle_function_call(tool_name, args or {})
                except Exception as exc:
                    logger.exception("tool %s raised", tool_name)
                    return json.dumps({"error": str(exc), "tool": tool_name})

            _dispatch.__name__ = tool_name
            _dispatch.__doc__ = tool_description
            _dispatch.__signature__ = sig
            _dispatch.__annotations__ = {**annots, "return": str}
            return _dispatch

        handler = _make_handler(name, params_schema, description)
        try:
            mcp.add_tool(handler, name=name, description=description)
        except TypeError:
            # Older MCP SDK signature — fall back to decorator-style.
            handler = mcp.tool(name=name, description=description)(handler)

        exposed_count += 1

    logger.info(
        "hermes-tools MCP server mode=%s registered %d/%d tools (%d available in registry)",
        mode,
        exposed_count,
        len(tool_names),
        len(all_defs),
    )
    return mcp


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for `python -m agent.transports.hermes_tools_mcp_server`."""
    argv = argv or sys.argv[1:]
    verbose = "--verbose" in argv or "-v" in argv

    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        stream=sys.stderr,  # MCP uses stdio for protocol — logs MUST go to stderr
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Quiet mode: keep Hermes' own banners off stdout (which is the MCP wire).
    os.environ.setdefault("HERMES_QUIET", "1")
    os.environ.setdefault("HERMES_REDACT_SECRETS", "true")

    try:
        server = _build_server()
    except ImportError as exc:
        sys.stderr.write(f"hermes-tools MCP server cannot start: {exc}\n")
        return 2

    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.exception("hermes-tools MCP server crashed")
        sys.stderr.write(f"hermes-tools MCP server error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
