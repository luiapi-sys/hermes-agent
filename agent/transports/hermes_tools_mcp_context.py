"""Context bridge for agent-loop Hermes tools exposed over MCP.

Most Hermes tools can be routed through ``model_tools.handle_function_call``
directly. Four tools are special: ``todo``, ``memory``, ``session_search`` and
``delegate_task``. Their registered handlers expect per-agent state that the
normal Hermes conversation loop injects when it executes them.

Full-mode MCP runs outside that loop, so this module supplies the smallest
equivalent context while preserving the *same* ``handle_function_call``
pipeline used by ordinary tools. This matters because that dispatcher owns
argument coercion, request/execution middleware, plugin approvals, observability
hooks and result transforms.

Implementation notes:

* A thread-local, one-shot membership bypass lets the current MCP invocation
  pass the ``_AGENT_LOOP_TOOLS`` guard inside ``handle_function_call`` without
  changing normal behavior in other threads or later nested calls.
* The registered handlers are wrapped once, process-locally, so the active MCP
  context is added only when the normal registry dispatch reaches that tool.
  Existing handler kwargs win via ``setdefault``; real child ``AIAgent`` state
  therefore takes precedence during delegation.
* ``todo`` gets a process-local ``TodoStore``.
* ``memory`` gets the normal profile-scoped, file-backed ``MemoryStore``.
* ``session_search`` gets ``SessionDB`` plus optional ``HERMES_MCP_SESSION_ID``.
* ``delegate_task`` gets a lightweight parent-runtime adapter; the existing
  delegation implementation still creates real child ``AIAgent`` instances.
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from contextlib import nullcontext
from typing import Any

logger = logging.getLogger(__name__)

AGENT_LOOP_TOOLS = frozenset({"todo", "memory", "session_search", "delegate_task"})
MCP_SESSION_ENV = "HERMES_MCP_SESSION_ID"

# These hooks are process-local. The MCP server is a dedicated subprocess, so
# installing them cannot widen tool behavior in the parent Hermes/Codex process.
_MCP_DISPATCH_LOCAL = threading.local()
_HOOK_INSTALL_LOCK = threading.Lock()


class _AgentLoopToolSetProxy(set):
    """Set preserving normal membership except for one MCP call's first check."""

    def __contains__(self, item: object) -> bool:
        counts = getattr(_MCP_DISPATCH_LOCAL, "bypass_once", None)
        if isinstance(counts, dict):
            remaining = counts.get(item, 0)
            if remaining > 0:
                counts[item] = remaining - 1
                return False
        return super().__contains__(item)


def _ensure_model_tools_context_hooks() -> None:
    """Install process-local hooks that keep execution inside model_tools.

    The wrappers are idempotent and intentionally do not alter schemas or tool
    names. Hooks/middleware therefore continue to observe the canonical Hermes
    tool name (``memory``, ``delegate_task``, etc.), not an MCP alias.
    """
    import model_tools
    from tools.registry import registry

    with _HOOK_INSTALL_LOCK:
        current_agent_loop_tools = getattr(model_tools, "_AGENT_LOOP_TOOLS", set())
        if not isinstance(current_agent_loop_tools, _AgentLoopToolSetProxy):
            model_tools._AGENT_LOOP_TOOLS = _AgentLoopToolSetProxy(
                current_agent_loop_tools
            )

        registry_lock = getattr(registry, "_lock", None)
        lock_context = registry_lock if registry_lock is not None else nullcontext()
        with lock_context:
            for tool_name in AGENT_LOOP_TOOLS:
                entry = registry.get_entry(tool_name)
                if entry is None:
                    continue
                handler = entry.handler
                if getattr(handler, "_hermes_mcp_context_wrapper", False):
                    continue

                def _wrapped_handler(
                    args: dict,
                    _original=handler,
                    _tool_name=tool_name,
                    **kwargs: Any,
                ):
                    active = getattr(_MCP_DISPATCH_LOCAL, "active", None)
                    if (
                        isinstance(active, tuple)
                        and len(active) == 2
                        and active[0] == _tool_name
                        and isinstance(active[1], dict)
                    ):
                        # Existing kwargs (e.g. a real child AIAgent's
                        # parent_agent/store) always win over MCP fallback state.
                        for key, value in active[1].items():
                            kwargs.setdefault(key, value)
                    return _original(args, **kwargs)

                _wrapped_handler._hermes_mcp_context_wrapper = True
                _wrapped_handler._hermes_mcp_original_handler = handler
                entry.handler = _wrapped_handler


class _DelegateParentContext:
    """Minimal parent surface consumed by ``tools.delegate_tool``.

    This is not an ``AIAgent`` and never runs its own model loop. It only holds
    runtime/session attributes that ``delegate_task`` inherits while building
    real child agents.
    """

    def __init__(self, *, session_db: Any = None, available_tool_names: tuple[str, ...] = ()):
        from hermes_cli.config import load_config
        from hermes_cli.fallback_config import get_fallback_chain
        from hermes_cli.runtime_provider import resolve_runtime_provider

        cfg = load_config() or {}
        model_cfg = cfg.get("model") or {}
        if isinstance(model_cfg, str):
            configured_model = model_cfg
            configured_provider = ""
            max_tokens = None
            request_overrides = {}
        else:
            configured_model = model_cfg.get("default") or model_cfg.get("model") or ""
            configured_provider = str(model_cfg.get("provider") or "").strip()
            max_tokens = model_cfg.get("max_tokens")
            request_overrides = model_cfg.get("request_overrides") or {}

        effective_model = (
            os.environ.get("HERMES_INFERENCE_MODEL", "").strip()
            or str(configured_model or "").strip()
        )
        requested_provider = (
            os.environ.get("HERMES_INFERENCE_PROVIDER", "").strip()
            or configured_provider
            or None
        )
        runtime = resolve_runtime_provider(
            requested=requested_provider,
            target_model=effective_model or None,
        ) or {}

        self.model = effective_model
        self.api_key = runtime.get("api_key")
        self.base_url = runtime.get("base_url")
        self.provider = runtime.get("provider")
        self.requested_provider = runtime.get("requested_provider")
        self.api_mode = runtime.get("api_mode")
        self._credential_pool = runtime.get("credential_pool")
        self._client_kwargs = {
            "api_key": self.api_key,
            "base_url": self.base_url,
        }

        # None means "all toolsets" in normal Hermes runtime. Delegation falls
        # back to valid_tool_names to derive the effective set.
        self.enabled_toolsets = None
        self.disabled_toolsets = None
        self.valid_tool_names = set(available_tool_names)

        self._fallback_chain = get_fallback_chain(cfg) or []
        self.max_tokens = max_tokens if isinstance(max_tokens, int) else None
        self.request_overrides = (
            dict(request_overrides) if isinstance(request_overrides, dict) else {}
        )
        self.reasoning_config = None
        self.prefill_messages = None
        self.providers_allowed = None
        self.providers_ignored = None
        self.providers_order = None
        self.provider_sort = None
        self.provider_require_parameters = False
        self.provider_data_collection = ""
        self.openrouter_min_coding_score = None
        self.acp_command = None
        self.acp_args = []

        self._session_db = session_db
        # Do not invent a parent session id. If the MCP host has a real Hermes
        # session it can provide it explicitly; otherwise children remain
        # standalone and avoid an invalid parent-session FK.
        self.session_id = os.environ.get(MCP_SESSION_ENV, "").strip() or None
        self._current_turn_id = ""
        self._current_task_id = None
        self._delegate_depth = 0
        self._subagent_id = None
        self._delegate_spinner = None
        self.tool_progress_callback = None
        self._print_fn = self._safe_print
        self._interrupt_requested = False

        self._active_children: list[Any] = []
        self._active_children_lock = threading.RLock()
        self._subagent_finalization_lock = threading.RLock()

    def _safe_print(self, *args: Any, **kwargs: Any) -> None:
        """Keep delegate progress off stdout, which is the MCP stdio wire."""
        kwargs.pop("file", None)
        print(*args, file=sys.stderr, **kwargs)

    def _touch_activity(self, *args: Any, **kwargs: Any) -> None:
        """Compatibility no-op for delegation heartbeat propagation."""


class MCPAgentContextBridge:
    """Provide missing state while preserving model_tools dispatch semantics."""

    def __init__(self, *, available_tool_names: tuple[str, ...] = ()) -> None:
        self._lock = threading.RLock()
        self._todo_store: Any = None
        self._memory_store: Any = None
        self._session_db: Any = None
        self._delegate_parent: Any = None
        self._available_tool_names = tuple(available_tool_names)
        atexit.register(self.close)

    @staticmethod
    def supports(tool_name: str) -> bool:
        return tool_name in AGENT_LOOP_TOOLS

    def _get_todo_store(self) -> Any:
        with self._lock:
            if self._todo_store is None:
                from tools.todo_tool import TodoStore

                self._todo_store = TodoStore()
            return self._todo_store

    def _get_memory_store(self) -> Any:
        with self._lock:
            if self._memory_store is None:
                from tools.memory_tool import MemoryStore

                store = MemoryStore()
                store.load_from_disk()
                self._memory_store = store
            return self._memory_store

    def _get_session_db(self) -> Any:
        with self._lock:
            if self._session_db is None:
                try:
                    from hermes_state import SessionDB

                    self._session_db = SessionDB()
                except Exception as exc:
                    logger.warning("MCP agent-context SessionDB unavailable: %s", exc)
                    self._session_db = False
            return None if self._session_db is False else self._session_db

    def _get_delegate_parent(self) -> _DelegateParentContext:
        with self._lock:
            if self._delegate_parent is None:
                self._delegate_parent = _DelegateParentContext(
                    session_db=self._get_session_db(),
                    available_tool_names=self._available_tool_names,
                )
            return self._delegate_parent

    def _context_for(self, tool_name: str) -> dict[str, Any]:
        if tool_name == "todo":
            return {"store": self._get_todo_store()}
        if tool_name == "memory":
            return {"store": self._get_memory_store()}
        if tool_name == "session_search":
            return {
                "db": self._get_session_db(),
                "current_session_id": (
                    os.environ.get(MCP_SESSION_ENV, "").strip() or None
                ),
            }
        if tool_name == "delegate_task":
            # MCP/tool-only channels cannot receive detached subagent
            # completions. Match hermes -z and force inline/synchronous delivery.
            from gateway.session_context import declare_stateless_channel

            declare_stateless_channel()
            return {"parent_agent": self._get_delegate_parent()}
        raise ValueError(f"{tool_name!r} is not an agent-loop MCP bridge tool")

    def dispatch(self, tool_name: str, args: dict[str, Any]) -> str | dict:
        """Execute an agent-loop tool through ``model_tools.handle_function_call``."""
        if tool_name not in AGENT_LOOP_TOOLS:
            raise ValueError(f"{tool_name!r} is not an agent-loop MCP bridge tool")

        _ensure_model_tools_context_hooks()
        context = self._context_for(tool_name)
        session_id = os.environ.get(MCP_SESSION_ENV, "").strip() or None

        previous_active = getattr(_MCP_DISPATCH_LOCAL, "active", None)
        previous_counts = dict(
            getattr(_MCP_DISPATCH_LOCAL, "bypass_once", {}) or {}
        )
        next_counts = dict(previous_counts)
        next_counts[tool_name] = next_counts.get(tool_name, 0) + 1
        _MCP_DISPATCH_LOCAL.active = (tool_name, context)
        _MCP_DISPATCH_LOCAL.bypass_once = next_counts

        try:
            from model_tools import handle_function_call

            return handle_function_call(
                tool_name,
                args,
                session_id=session_id,
            )
        finally:
            _MCP_DISPATCH_LOCAL.active = previous_active
            _MCP_DISPATCH_LOCAL.bypass_once = previous_counts

    def close(self) -> None:
        with self._lock:
            db = self._session_db
            self._session_db = None
            if db and db is not False:
                try:
                    db.close()
                except Exception:
                    pass


__all__ = [
    "AGENT_LOOP_TOOLS",
    "MCPAgentContextBridge",
    "MCP_SESSION_ENV",
]
