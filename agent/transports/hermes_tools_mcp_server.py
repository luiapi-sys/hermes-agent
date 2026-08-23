"""Hermes-tools-as-MCP server for the codex_app_server runtime.

When the user runs `openai/*` turns through the codex app-server, codex
owns the loop and builds its own tool list. By default, that means
Hermes' richer tool surface is unreachable unless it is bridged through MCP.

User-facing behavior is configured in ``config.yaml`` under
``mcp.hermes_tools``::

    mcp:
      hermes_tools:
        mode: full
        discover_external: true
        allow_native_execution: false

``mode: curated`` (default)
    Preserve the historical Codex-oriented allowlist. Tools that duplicate
    Codex built-ins remain hidden and agent-loop tools stay out of the MCP
    surface.

``mode: full``
    Expose every currently available Hermes tool definition from the registry,
    including configured external MCP tools and the stateful agent-loop tools
    supported by the MCP context bridge.

For security, full mode filters registry tools carrying host-execution,
filesystem, process-control, UI-automation, agent-spawn, worker-spawn, or
external-MCP capabilities by default. Classification lives in the central tool registry so
future tools inherit the boundary from their toolset or explicit metadata. A
trusted external MCP deployment (for example a dedicated ChatGPT remote MCP
gateway) that intentionally wants the complete native surface must also set
``mcp.hermes_tools.allow_native_execution: true``.

``HERMES_MCP_MODE``, ``HERMES_MCP_DISCOVER_EXTERNAL`` and
``HERMES_MCP_ALLOW_NATIVE_EXECUTION`` remain supported as process-local/internal
or legacy overrides, but behavioral configuration should live in config.yaml.

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
from typing import Any, Collection, Mapping, Optional

from tools.registry import ToolCapability, registry

logger = logging.getLogger(__name__)

MCP_MODE_ENV = "HERMES_MCP_MODE"
MCP_DISCOVER_EXTERNAL_ENV = "HERMES_MCP_DISCOVER_EXTERNAL"
MCP_ALLOW_NATIVE_EXECUTION_ENV = "HERMES_MCP_ALLOW_NATIVE_EXECUTION"
MCP_MODE_CURATED = "curated"
MCP_MODE_FULL = "full"
_VALID_MCP_MODES = {MCP_MODE_CURATED, MCP_MODE_FULL}

# Security capabilities that can escape a coding client's own sandbox or
# approval boundary. The registry, not this transport, owns tool classification.
_MCP_UNSAFE_CAPABILITIES: frozenset[str] = frozenset(
    {
        ToolCapability.HOST_EXECUTION,
        ToolCapability.FILESYSTEM_ACCESS,
        ToolCapability.PROCESS_CONTROL,
        ToolCapability.UI_AUTOMATION,
        ToolCapability.SPAWN_AGENT,
        ToolCapability.SPAWN_WORKER,
        ToolCapability.EXTERNAL_MCP,
        ToolCapability.REMOTE_MUTATION,
    }
)

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


def _load_hermes_tools_config() -> dict[str, Any]:
    """Load the profile-aware ``mcp.hermes_tools`` config block.

    Config loading is best-effort because this MCP subprocess must still be
    able to start in a fresh/minimal environment. Invalid/missing structure
    falls back to the safe curated defaults below.
    """
    try:
        from hermes_cli.config import load_config

        config = load_config() or {}
    except Exception as exc:
        logger.warning("failed to load MCP config; using safe defaults: %s", exc)
        return {}

    mcp_cfg = config.get("mcp") or {}
    if not isinstance(mcp_cfg, dict):
        return {}
    tools_cfg = mcp_cfg.get("hermes_tools") or {}
    return tools_cfg if isinstance(tools_cfg, dict) else {}


def _resolve_mcp_mode(
    value: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """Resolve and validate the MCP exposure mode.

    The user-facing source is ``config.yaml``. ``HERMES_MCP_MODE`` is retained
    as an internal/backward-compatible process override for transports that
    need to bridge a resolved value into a subprocess.

    Invalid values fail closed to curated mode instead of widening the tool
    surface accidentally.
    """
    cfg = config if config is not None else _load_hermes_tools_config()
    if value is not None:
        raw = value
    elif MCP_MODE_ENV in os.environ:
        raw = os.environ.get(MCP_MODE_ENV)
    else:
        raw = cfg.get("mode", MCP_MODE_CURATED)

    mode = str(raw or MCP_MODE_CURATED).strip().lower()
    if mode not in _VALID_MCP_MODES:
        logger.warning(
            "invalid MCP mode=%r; falling back to %s",
            raw,
            MCP_MODE_CURATED,
        )
        return MCP_MODE_CURATED
    return mode


def _resolve_discover_external(
    *,
    config: dict[str, Any] | None = None,
) -> bool:
    cfg = config if config is not None else _load_hermes_tools_config()
    if MCP_DISCOVER_EXTERNAL_ENV in os.environ:
        return _env_bool(MCP_DISCOVER_EXTERNAL_ENV, True)
    value = cfg.get("discover_external", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    logger.warning("invalid mcp.hermes_tools.discover_external=%r; using true", value)
    return True


def _resolve_allow_native_execution(
    *,
    config: dict[str, Any] | None = None,
) -> bool:
    cfg = config if config is not None else _load_hermes_tools_config()
    if MCP_ALLOW_NATIVE_EXECUTION_ENV in os.environ:
        return _env_bool(MCP_ALLOW_NATIVE_EXECUTION_ENV, False)
    value = cfg.get("allow_native_execution", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    logger.warning(
        "invalid mcp.hermes_tools.allow_native_execution=%r; using false",
        value,
    )
    return False


def _resolve_exposed_tool_names(
    all_defs: dict[str, dict],
    *,
    mode: str | None = None,
    allow_native_execution: bool = True,
    capabilities_by_name: Mapping[str, Collection[str]] | None = None,
) -> tuple[str, ...]:
    """Return tool names exposed by the selected MCP capability policy.

    ``all_defs`` remains the authoritative availability snapshot. In safe full
    mode, tools carrying any security-sensitive registry capability are removed
    regardless of their concrete name. Production startup passes a capability
    snapshot from the same registry generation used to build ``all_defs``.
    """
    resolved_mode = _resolve_mcp_mode(mode)
    if resolved_mode == MCP_MODE_FULL:
        if allow_native_execution:
            return tuple(sorted(all_defs))
        caps = capabilities_by_name or {}
        return tuple(
            sorted(
                name
                for name in all_defs
                if not (_MCP_UNSAFE_CAPABILITIES & frozenset(caps.get(name, ())))
            )
        )
    return EXPOSED_TOOLS


def _discover_external_mcp_tools(
    mode: str,
    *,
    enabled: bool | None = None,
    allow_native_execution: bool = False,
) -> None:
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
    if enabled is None:
        enabled = _resolve_discover_external()
    if not enabled:
        logger.info("external MCP discovery disabled by config")
        return
    if not allow_native_execution:
        logger.info(
            "external MCP discovery suppressed because "
            "allow_native_execution is false"
        )
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

    mcp_config = _load_hermes_tools_config()
    mode = _resolve_mcp_mode(config=mcp_config)
    discover_external = _resolve_discover_external(config=mcp_config)
    allow_native_execution = _resolve_allow_native_execution(config=mcp_config)

    # Plugin import executes user/project/pip code. Resolve trust first and
    # suppress plugin discovery before importing model_tools unless this MCP
    # process has the explicit trusted execution opt-in.
    if not allow_native_execution:
        os.environ["HERMES_SKIP_PLUGIN_DISCOVERY"] = "1"
    else:
        os.environ.pop("HERMES_SKIP_PLUGIN_DISCOVERY", None)

    from model_tools import get_tool_definitions, handle_function_call

    if allow_native_execution:
        try:
            from hermes_cli.plugins import discover_plugins

            discover_plugins()
        except Exception as exc:
            logger.debug("Trusted MCP plugin discovery failed: %s", exc)

    mcp = FastMCP(
        "hermes-tools",
        instructions=(
            "Hermes Agent tool surface exposed over MCP. Curated mode contains "
            "the Codex-safe Hermes-specific subset. Full mode contains every "
            "currently available built-in, plugin and configured external MCP "
            "registry tool allowed by the MCP policy. Stateful agent-loop tools "
            "are supported through the MCP context bridge. Tools carrying native "
            "execution, filesystem, process, UI-automation, or spawn capabilities "
            "are included only when allow_native_execution is explicitly enabled."
        ),
    )

    # model_tools deliberately does not discover configured MCP servers at
    # import time. Full mode is a dedicated MCP process with a static tool list,
    # so discovery must finish before taking the authoritative registry snapshot.
    _discover_external_mcp_tools(
        mode,
        enabled=discover_external,
        allow_native_execution=allow_native_execution,
    )

    # Always request the raw pre-Tool-Search catalog. Otherwise progressive
    # disclosure can replace real tools with tool_search/tool_describe/tool_call
    # before this MCP adapter gets a chance to expose them.
    definition_kwargs = {
        "quiet_mode": True,
        "skip_tool_search_assembly": True,
    }
    if not allow_native_execution:
        definition_kwargs["excluded_capabilities"] = set(_MCP_UNSAFE_CAPABILITIES)

    all_defs = {
        td["function"]["name"]: td["function"]
        for td in (
            get_tool_definitions(**definition_kwargs)
            or []
        )
        if (
            isinstance(td, dict)
            and td.get("type") == "function"
            and isinstance(td.get("function"), dict)
            and td["function"].get("name")
        )
    }

    capabilities_by_name = {
        name: registry.get_tool_capabilities(name)
        for name in all_defs
    }
    tool_names = _resolve_exposed_tool_names(
        all_defs,
        mode=mode,
        allow_native_execution=allow_native_execution,
        capabilities_by_name=capabilities_by_name,
    )

    # Only full mode needs the stateful bridge. Curated mode keeps the exact
    # historical Codex behavior and never initializes memory/session/delegation
    # context as a side effect. The bridge receives only policy-exposed names so
    # future context-sensitive tools cannot inherit hidden native capabilities.
    agent_context_bridge = None
    if mode == MCP_MODE_FULL:
        from agent.transports.hermes_tools_mcp_context import MCPAgentContextBridge

        agent_context_bridge = MCPAgentContextBridge(
            available_tool_names=tuple(name for name in tool_names if name in all_defs),
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
        "hermes-tools MCP server mode=%s native_execution=%s registered %d/%d tools (%d available in registry)",
        mode,
        allow_native_execution,
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
