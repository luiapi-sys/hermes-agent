"""Context bridge for agent-loop Hermes tools exposed over MCP.

Most Hermes tools are stateless from the MCP adapter's perspective and can be
routed through ``model_tools.handle_function_call`` directly. Four tools are
special: ``todo``, ``memory``, ``session_search`` and ``delegate_task``. Their
registered handlers expect per-agent state that the normal Hermes conversation
loop injects when it executes them.

The full MCP surface runs outside that loop, so this module supplies the
smallest equivalent context without changing the normal CLI/gateway runtime:

* ``todo`` gets a process-local ``TodoStore`` (one stdio MCP process = one
  client session unless ``HERMES_MCP_SESSION_ID`` is explicitly reused).
* ``memory`` gets the normal file-backed ``MemoryStore`` loaded from the active
  Hermes profile.
* ``session_search`` gets the normal ``SessionDB`` plus an optional current
  session id from ``HERMES_MCP_SESSION_ID``.
* ``delegate_task`` gets a lightweight parent-agent adapter carrying the
  configured model/provider/runtime state. The delegate implementation still
  constructs real child ``AIAgent`` instances; this adapter only provides the
  parent attributes that delegation normally inherits.

The bridge deliberately dispatches through the registered tool handlers rather
than reimplementing tool semantics. This keeps the source of truth in
``tools/*_tool.py`` and limits the MCP-specific code to context construction.
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)

AGENT_LOOP_TOOLS = frozenset({"todo", "memory", "session_search", "delegate_task"})
MCP_SESSION_ENV = "HERMES_MCP_SESSION_ID"


class _DelegateParentContext:
    """Minimal parent surface consumed by ``tools.delegate_tool``.

    This is not an ``AIAgent`` and never runs its own model loop. It only holds
    the runtime/session attributes that ``delegate_task`` inherits while
    constructing real child agents.
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

        # None means "all toolsets" in the normal Hermes runtime. The
        # delegate code falls back to valid_tool_names to derive the effective
        # set, so keep the raw full-MCP catalog here.
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
        # session it can provide it explicitly; otherwise children are simply
        # standalone subagent sessions and avoid an invalid parent FK.
        self.session_id = os.environ.get(MCP_SESSION_ENV, "").strip() or None
        self._current_turn_id = ""
        self._delegate_depth = 0
        self._subagent_id = None
        self._delegate_spinner = None
        self.tool_progress_callback = None
        self._print_fn = self._safe_print

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
    """Provide missing context for the four Hermes agent-loop tools."""

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

    def dispatch(self, tool_name: str, args: dict[str, Any]) -> str | dict:
        """Dispatch one agent-loop tool through its registered Hermes handler."""
        if tool_name not in AGENT_LOOP_TOOLS:
            raise ValueError(f"{tool_name!r} is not an agent-loop MCP bridge tool")

        from tools.registry import registry

        if tool_name == "todo":
            # TodoStore is intentionally mutable process-local state; serialize
            # calls so parallel MCP requests cannot interleave writes.
            with self._lock:
                return registry.dispatch(tool_name, args, store=self._get_todo_store())

        if tool_name == "memory":
            return registry.dispatch(tool_name, args, store=self._get_memory_store())

        if tool_name == "session_search":
            return registry.dispatch(
                tool_name,
                args,
                db=self._get_session_db(),
                current_session_id=os.environ.get(MCP_SESSION_ENV, "").strip() or None,
            )

        # Remote/tool-only MCP channels cannot receive detached subagent
        # completion events. Mark this process as stateless so delegate_task
        # follows its synchronous/inline delivery path, exactly like hermes -z.
        from gateway.session_context import declare_stateless_channel

        declare_stateless_channel()
        return registry.dispatch(
            tool_name,
            args,
            parent_agent=self._get_delegate_parent(),
        )

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
