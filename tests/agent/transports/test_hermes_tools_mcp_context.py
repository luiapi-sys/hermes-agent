from __future__ import annotations

from agent.transports.hermes_tools_mcp_context import (
    AGENT_LOOP_TOOLS,
    MCPAgentContextBridge,
    MCP_SESSION_ENV,
    _DelegateParentContext,
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


def test_todo_dispatch_injects_store(monkeypatch):
    from tools.registry import registry

    bridge = MCPAgentContextBridge()
    store = object()
    bridge._todo_store = store
    seen = {}

    def fake_dispatch(name, args, **kwargs):
        seen.update(name=name, args=args, kwargs=kwargs)
        return "ok"

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    assert bridge.dispatch("todo", {"todos": []}) == "ok"
    assert seen["name"] == "todo"
    assert seen["kwargs"]["store"] is store
    bridge.close()


def test_memory_dispatch_injects_store(monkeypatch):
    from tools.registry import registry

    bridge = MCPAgentContextBridge()
    store = object()
    bridge._memory_store = store
    seen = {}

    def fake_dispatch(name, args, **kwargs):
        seen.update(name=name, args=args, kwargs=kwargs)
        return "ok"

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    assert bridge.dispatch("memory", {"action": "add", "content": "x"}) == "ok"
    assert seen["name"] == "memory"
    assert seen["kwargs"]["store"] is store
    bridge.close()


def test_session_search_dispatch_injects_db_and_current_session(monkeypatch):
    from tools.registry import registry

    bridge = MCPAgentContextBridge()
    db = object()
    bridge._session_db = db
    monkeypatch.setenv(MCP_SESSION_ENV, "mcp-session-123")
    seen = {}

    def fake_dispatch(name, args, **kwargs):
        seen.update(name=name, args=args, kwargs=kwargs)
        return "ok"

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    assert bridge.dispatch("session_search", {"query": "deploy"}) == "ok"
    assert seen["name"] == "session_search"
    assert seen["kwargs"]["db"] is db
    assert seen["kwargs"]["current_session_id"] == "mcp-session-123"
    bridge.close()


def test_delegate_dispatch_injects_parent_and_declares_stateless(monkeypatch):
    from gateway import session_context
    from tools.registry import registry

    bridge = MCPAgentContextBridge(available_tool_names=("terminal", "read_file"))
    parent = object()
    bridge._delegate_parent = parent
    declared = []
    seen = {}

    monkeypatch.setattr(
        session_context,
        "declare_stateless_channel",
        lambda: declared.append(True),
    )

    def fake_dispatch(name, args, **kwargs):
        seen.update(name=name, args=args, kwargs=kwargs)
        return "ok"

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    assert bridge.dispatch("delegate_task", {"goal": "inspect project"}) == "ok"
    assert declared == [True]
    assert seen["name"] == "delegate_task"
    assert seen["kwargs"]["parent_agent"] is parent
    bridge.close()


def test_unknown_tool_is_rejected_before_registry_dispatch():
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
