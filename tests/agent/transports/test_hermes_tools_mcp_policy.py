"""Policy tests for Hermes full-surface MCP exposure."""

from __future__ import annotations

from agent.transports.hermes_tools_mcp_server import (
    MCP_ALLOW_NATIVE_EXECUTION_ENV,
    MCP_DISCOVER_EXTERNAL_ENV,
    MCP_MODE_CURATED,
    MCP_MODE_FULL,
    _MCP_UNSAFE_CAPABILITIES,
    _load_hermes_tools_config,
    _resolve_allow_native_execution,
    _resolve_discover_external,
    _resolve_exposed_tool_names,
    _resolve_mcp_mode,
)
from tools.registry import ToolCapability, ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {}},
    }


def test_profile_config_is_primary_user_facing_source(monkeypatch):
    import hermes_cli.config as config_module

    monkeypatch.delenv("HERMES_MCP_MODE", raising=False)
    monkeypatch.delenv(MCP_DISCOVER_EXTERNAL_ENV, raising=False)
    monkeypatch.delenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, raising=False)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: {
            "mcp": {
                "hermes_tools": {
                    "mode": "full",
                    "discover_external": False,
                    "allow_native_execution": True,
                }
            }
        },
    )

    cfg = _load_hermes_tools_config()
    assert cfg == {
        "mode": "full",
        "discover_external": False,
        "allow_native_execution": True,
    }
    assert _resolve_mcp_mode(config=cfg) == MCP_MODE_FULL
    assert _resolve_discover_external(config=cfg) is False
    assert _resolve_allow_native_execution(config=cfg) is True


def test_missing_config_fails_closed(monkeypatch):
    monkeypatch.delenv("HERMES_MCP_MODE", raising=False)
    monkeypatch.delenv(MCP_DISCOVER_EXTERNAL_ENV, raising=False)
    monkeypatch.delenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, raising=False)

    assert _resolve_mcp_mode(config={}) == MCP_MODE_CURATED
    assert _resolve_discover_external(config={}) is True
    assert _resolve_allow_native_execution(config={}) is False


def test_legacy_process_override_remains_supported(monkeypatch):
    monkeypatch.setenv("HERMES_MCP_MODE", "full")
    monkeypatch.setenv(MCP_DISCOVER_EXTERNAL_ENV, "0")
    monkeypatch.setenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, "1")

    cfg = {
        "mode": "curated",
        "discover_external": True,
        "allow_native_execution": False,
    }
    assert _resolve_mcp_mode(config=cfg) == MCP_MODE_FULL
    assert _resolve_discover_external(config=cfg) is False
    assert _resolve_allow_native_execution(config=cfg) is True


def test_registry_toolset_defaults_classify_native_execution_surfaces():
    reg = ToolRegistry()
    cases = (
        ("terminal", "terminal", ToolCapability.HOST_EXECUTION),
        ("read_file", "file", ToolCapability.FILESYSTEM_ACCESS),
        ("execute_code", "code_execution", ToolCapability.HOST_EXECUTION),
        ("computer_use", "computer_use", ToolCapability.UI_AUTOMATION),
        ("delegate_task", "delegation", ToolCapability.SPAWN_AGENT),
        ("cronjob", "cronjob", ToolCapability.SPAWN_AGENT),
    )
    for name, toolset, expected in cases:
        reg.register(
            name=name,
            toolset=toolset,
            schema=_schema(name),
            handler=lambda args, **kw: "",
        )
        assert expected in reg.get_tool_capabilities(name)


def test_explicit_capabilities_union_with_toolset_defaults():
    reg = ToolRegistry()
    reg.register(
        name="future_terminal_worker",
        toolset="terminal",
        schema=_schema("future_terminal_worker"),
        handler=lambda args, **kw: "",
        capabilities={ToolCapability.SPAWN_WORKER},
    )
    caps = reg.get_tool_capabilities("future_terminal_worker")
    assert ToolCapability.HOST_EXECUTION in caps
    assert ToolCapability.PROCESS_CONTROL in caps
    assert ToolCapability.SPAWN_WORKER in caps


def test_safe_full_filters_by_capability_not_concrete_tool_name():
    defs = {
        "future_ui_tool": {},
        "future_worker_tool": {},
        "memory": {},
        "external_mcp_tool": {},
    }
    caps = {
        "future_ui_tool": {ToolCapability.UI_AUTOMATION},
        "future_worker_tool": {ToolCapability.SPAWN_WORKER},
        "memory": {ToolCapability.MCP_SAFE},
        "external_mcp_tool": {ToolCapability.EXTERNAL_MCP},
    }
    exposed = set(
        _resolve_exposed_tool_names(
            defs,
            mode="full",
            allow_native_execution=False,
            capabilities_by_name=caps,
        )
    )
    assert "future_ui_tool" not in exposed
    assert "future_worker_tool" not in exposed
    assert "external_mcp_tool" not in exposed
    assert "memory" in exposed


def test_trusted_full_includes_capability_marked_tools():
    defs = {"terminal": {}, "computer_use": {}, "kanban_create": {}, "memory": {}}
    caps = {
        "terminal": {ToolCapability.HOST_EXECUTION},
        "computer_use": {ToolCapability.UI_AUTOMATION},
        "kanban_create": {ToolCapability.SPAWN_WORKER},
        "memory": set(),
    }
    assert set(
        _resolve_exposed_tool_names(
            defs,
            mode="full",
            allow_native_execution=True,
            capabilities_by_name=caps,
        )
    ) == set(defs)


def test_unsafe_capability_set_covers_execution_and_spawn_classes():
    assert {
        ToolCapability.HOST_EXECUTION,
        ToolCapability.FILESYSTEM_ACCESS,
        ToolCapability.PROCESS_CONTROL,
        ToolCapability.UI_AUTOMATION,
        ToolCapability.SPAWN_AGENT,
        ToolCapability.SPAWN_WORKER,
        ToolCapability.EXTERNAL_MCP,
    } <= _MCP_UNSAFE_CAPABILITIES


def test_registered_escape_surfaces_are_classified():
    import model_tools  # noqa: F401 - triggers built-in tool discovery
    from tools.registry import registry

    expected = {
        "terminal": ToolCapability.HOST_EXECUTION,
        "process": ToolCapability.PROCESS_CONTROL,
        "read_file": ToolCapability.FILESYSTEM_ACCESS,
        "write_file": ToolCapability.FILESYSTEM_ACCESS,
        "patch": ToolCapability.FILESYSTEM_ACCESS,
        "search_files": ToolCapability.FILESYSTEM_ACCESS,
        "execute_code": ToolCapability.HOST_EXECUTION,
        "computer_use": ToolCapability.UI_AUTOMATION,
        "delegate_task": ToolCapability.SPAWN_AGENT,
        "cronjob": ToolCapability.SPAWN_AGENT,
        "kanban_create": ToolCapability.SPAWN_WORKER,
        "kanban_unblock": ToolCapability.SPAWN_WORKER,
        "kanban_complete": ToolCapability.SPAWN_WORKER,
    }
    for name, capability in expected.items():
        assert capability in registry.get_tool_capabilities(name), name



def test_safe_full_is_explicit_allow_and_fail_closed_for_unclassified_tools():
    from agent.transports.hermes_tools_mcp_server import _resolve_exposed_tool_names
    from tools.registry import ToolCapability

    all_defs = {
        "reviewed_safe": {"name": "reviewed_safe"},
        "new_unclassified_tool": {"name": "new_unclassified_tool"},
        "unsafe": {"name": "unsafe"},
    }
    caps = {
        "reviewed_safe": {ToolCapability.MCP_SAFE},
        "new_unclassified_tool": set(),
        "unsafe": {ToolCapability.MCP_SAFE, ToolCapability.HOST_EXECUTION},
    }
    exposed = _resolve_exposed_tool_names(
        all_defs,
        mode="full",
        allow_native_execution=False,
        capabilities_by_name=caps,
    )
    assert exposed == ("reviewed_safe",)


def test_registry_capability_filter_runs_before_availability_probe():
    from tools.registry import ToolCapability, ToolRegistry

    calls = []
    reg = ToolRegistry()
    reg.register(
        name="unsafe_probe",
        toolset="custom",
        schema={"name": "unsafe_probe", "parameters": {"type": "object"}},
        handler=lambda args, **kwargs: "ok",
        check_fn=lambda: calls.append("probe") or True,
        capabilities={ToolCapability.HOST_EXECUTION},
    )
    assert reg.get_definitions(
        {"unsafe_probe"},
        exclude_capabilities={ToolCapability.HOST_EXECUTION},
    ) == []
    assert calls == []
