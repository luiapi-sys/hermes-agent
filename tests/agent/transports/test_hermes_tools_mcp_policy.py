"""Policy tests for Hermes full-surface MCP exposure."""

from __future__ import annotations

from agent.transports.hermes_tools_mcp_server import (
    MCP_ALLOW_NATIVE_EXECUTION_ENV,
    MCP_DISCOVER_EXTERNAL_ENV,
    MCP_MODE_CURATED,
    MCP_MODE_FULL,
    _NATIVE_BOUNDARY_TOOLS,
    _load_hermes_tools_config,
    _resolve_allow_native_execution,
    _resolve_discover_external,
    _resolve_exposed_tool_names,
    _resolve_mcp_mode,
)


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


def test_cronjob_is_part_of_native_execution_boundary():
    assert "cronjob" in _NATIVE_BOUNDARY_TOOLS


def test_full_mode_protects_native_boundary_without_explicit_opt_in():
    defs = {
        "terminal": {},
        "read_file": {},
        "write_file": {},
        "patch": {},
        "search_files": {},
        "process": {},
        "execute_code": {},
        "memory": {},
        "session_search": {},
        "todo": {},
        "delegate_task": {},
        "cronjob": {},
        "external_mcp_tool": {},
    }

    exposed = set(
        _resolve_exposed_tool_names(
            defs,
            mode="full",
            allow_native_execution=False,
        )
    )
    assert not (exposed & _NATIVE_BOUNDARY_TOOLS)
    assert "delegate_task" not in exposed
    assert "cronjob" not in exposed
    assert {"memory", "session_search", "todo", "external_mcp_tool"} <= exposed


def test_trusted_external_gateway_can_explicitly_enable_complete_surface():
    defs = {
        "terminal": {},
        "read_file": {},
        "write_file": {},
        "patch": {},
        "process": {},
        "execute_code": {},
        "memory": {},
        "session_search": {},
        "todo": {},
        "delegate_task": {},
        "cronjob": {},
        "external_mcp_tool": {},
    }

    assert set(
        _resolve_exposed_tool_names(
            defs,
            mode="full",
            allow_native_execution=True,
        )
    ) == set(defs)
