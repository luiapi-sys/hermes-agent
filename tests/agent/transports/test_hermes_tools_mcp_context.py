from __future__ import annotations

from agent.transports.hermes_tools_mcp_context import (
    AGENT_LOOP_TOOLS,
    MCPAgentContextBridge,
    MCP_SESSION_ENV,
    _AgentLoopToolSetProxy,
    _DelegateParentContext,
    _MCP_DISPATCH_LOCAL,
)


def test_bridge_supports_exact_agent_loop_tools():
    bridge = MCPAgentContextBridge()
    assert AGENT_LOOP_TOOLS == {
        "todo",
        "memory",
        "session_search",
        "delegate_task",
    }
    for name in AGENT_LOOP_TOOLS:
        assert bridge.supports(name)
    assert not bridge.supports("terminal")
    bridge.close()


def test_agent_loop_guard_bypass_is_one_shot_and_thread_local():
    proxy = _AgentLoopToolSetProxy({"todo", "memory"})
    previous = getattr(_MCP_DISPATCH_LOCAL, "bypass_once", None)
    try:
        _MCP_DISPATCH_LOCAL.bypass_once = {"todo": 1}
        assert "todo" not in proxy
        # The bypass is consumed by the first membership check only.
        assert "todo" in proxy
        assert "memory" in proxy
    finally:
        if previous is None:
            try:
                delattr(_MCP_DISPATCH_LOCAL, "bypass_once")
            except AttributeError:
                pass
        else:
            _MCP_DISPATCH_LOCAL.bypass_once = previous


def test_todo_context_contains_process_local_store():
    bridge = MCPAgentContextBridge()
    store = object()
    bridge._todo_store = store
    assert bridge._context_for("todo") == {"store": store}
    bridge.close()


def test_memory_context_contains_profile_store():
    bridge = MCPAgentContextBridge()
    store = object()
    bridge._memory_store = store
    assert bridge._context_for("memory") == {"store": store}
    bridge.close()


def test_session_search_context_contains_db_and_current_session(monkeypatch):
    bridge = MCPAgentContextBridge()
    db = object()
    bridge._session_db = db
    monkeypatch.setenv(MCP_SESSION_ENV, "mcp-session-123")

    context = bridge._context_for("session_search")
    assert context["db"] is db
    assert context["current_session_id"] == "mcp-session-123"
    bridge.close()


def test_delegate_context_contains_parent_and_declares_stateless(monkeypatch):
    from gateway import session_context

    bridge = MCPAgentContextBridge(available_tool_names=("terminal", "read_file"))
    parent = object()
    bridge._delegate_parent = parent
    declared = []

    monkeypatch.setattr(
        session_context,
        "declare_stateless_channel",
        lambda: declared.append(True),
    )

    context = bridge._context_for("delegate_task")
    assert declared == [True]
    assert context["parent_agent"] is parent
    bridge.close()


def test_dispatch_reenters_model_tools_and_injects_context_at_registry_handler(monkeypatch):
    """The MCP bridge must preserve handle_function_call as the dispatcher."""
    import model_tools
    from tools.registry import registry

    bridge = MCPAgentContextBridge()
    store = object()
    bridge._todo_store = store

    entry = registry.get_entry("todo")
    assert entry is not None
    seen = {}

    def original_handler(args, **kwargs):
        seen["handler_args"] = args
        seen["handler_kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(entry, "handler", original_handler)
    monkeypatch.setattr(
        model_tools,
        "_AGENT_LOOP_TOOLS",
        {"todo", "memory", "session_search", "delegate_task"},
    )

    def fake_handle_function_call(name, args, **kwargs):
        # Simulate the exact guard + registry-dispatch seam in model_tools.
        # The first membership test must be bypassed, then normal membership
        # must immediately return for later/nested calls.
        seen["guard_bypassed"] = name not in model_tools._AGENT_LOOP_TOOLS
        seen["guard_restored"] = name in model_tools._AGENT_LOOP_TOOLS
        seen["dispatcher_kwargs"] = kwargs
        return registry.get_entry(name).handler(args)

    monkeypatch.setattr(model_tools, "handle_function_call", fake_handle_function_call)

    assert bridge.dispatch("todo", {"todos": []}) == "ok"
    assert seen["guard_bypassed"] is True
    assert seen["guard_restored"] is True
    assert seen["handler_args"] == {"todos": []}
    assert seen["handler_kwargs"]["store"] is store
    bridge.close()


def test_existing_handler_context_wins_over_mcp_fallback(monkeypatch):
    """A real child AIAgent's state must not be overwritten by MCP fallback."""
    import model_tools
    from tools.registry import registry

    bridge = MCPAgentContextBridge()
    mcp_store = object()
    child_store = object()
    bridge._todo_store = mcp_store

    entry = registry.get_entry("todo")
    assert entry is not None
    seen = {}

    def original_handler(args, **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(entry, "handler", original_handler)
    monkeypatch.setattr(
        model_tools,
        "_AGENT_LOOP_TOOLS",
        {"todo", "memory", "session_search", "delegate_task"},
    )

    # Install the wrapper using bridge.dispatch infrastructure, but simulate a
    # nested/child handler invocation that already carries its own store.
    def fake_handle_function_call(name, args, **kwargs):
        assert name not in model_tools._AGENT_LOOP_TOOLS
        wrapped = registry.get_entry(name).handler
        return wrapped(args, store=child_store)

    monkeypatch.setattr(model_tools, "handle_function_call", fake_handle_function_call)

    assert bridge.dispatch("todo", {}) == "ok"
    assert seen["store"] is child_store
    bridge.close()


def test_unknown_tool_is_rejected_before_dispatch():
    bridge = MCPAgentContextBridge()
    try:
        bridge.dispatch("terminal", {})
    except ValueError as exc:
        assert "not an agent-loop MCP bridge tool" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    bridge.close()


def test_delegate_parent_resolves_runtime_from_config(monkeypatch):
    from hermes_cli import config as config_mod
    from hermes_cli import fallback_config as fallback_mod
    from hermes_cli import runtime_provider as runtime_mod

    monkeypatch.delenv("HERMES_INFERENCE_MODEL", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.delenv(MCP_SESSION_ENV, raising=False)

    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda: {
            "model": {
                "default": "model-x",
                "provider": "provider-x",
                "max_tokens": 4096,
                "request_overrides": {"temperature": 0.1},
            }
        },
    )
    monkeypatch.setattr(fallback_mod, "get_fallback_chain", lambda cfg: ["fallback-y"])
    monkeypatch.setattr(
        runtime_mod,
        "resolve_runtime_provider",
        lambda requested, target_model: {
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
            "provider": requested,
            "requested_provider": requested,
            "api_mode": "chat_completions",
            "credential_pool": "pool",
        },
    )

    parent = _DelegateParentContext(
        session_db="db",
        available_tool_names=("terminal", "read_file"),
    )

    assert parent.model == "model-x"
    assert parent.provider == "provider-x"
    assert parent.api_key == "test-key"
    assert parent.base_url == "https://example.invalid/v1"
    assert parent.api_mode == "chat_completions"
    assert parent.valid_tool_names == {"terminal", "read_file"}
    assert parent._fallback_chain == ["fallback-y"]
    assert parent.max_tokens == 4096
    assert parent.request_overrides == {"temperature": 0.1}
    assert parent._session_db == "db"
    assert parent.session_id is None
