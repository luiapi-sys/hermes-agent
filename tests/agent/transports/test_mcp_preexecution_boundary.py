"""Regression tests for MCP policy enforcement before executable discovery/probes."""

from __future__ import annotations

from tools.registry import ToolCapability, ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {}},
    }


def _handler(args, **kwargs):
    return "ok"


def test_registry_exclusion_skips_unsafe_availability_probe_entirely():
    reg = ToolRegistry()
    probes: list[str] = []

    reg.register(
        name="danger",
        toolset="test-danger",
        schema=_schema("danger"),
        handler=_handler,
        check_fn=lambda: probes.append("danger") or True,
        capabilities={ToolCapability.HOST_EXECUTION},
    )
    reg.register(
        name="safe",
        toolset="test-safe",
        schema=_schema("safe"),
        handler=_handler,
        check_fn=lambda: probes.append("safe") or True,
    )

    defs = reg.get_definitions(
        {"danger", "safe"},
        quiet=True,
        excluded_capabilities={ToolCapability.HOST_EXECUTION},
    )

    assert [item["function"]["name"] for item in defs] == ["safe"]
    assert probes == ["safe"]


def test_execution_toolsets_inherit_fail_closed_capabilities():
    reg = ToolRegistry()
    cases = {
        "browser": {
            ToolCapability.UI_AUTOMATION,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        },
        "tts": {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        },
        "discord": {ToolCapability.EXTERNAL_SIDE_EFFECT},
        "discord_admin": {ToolCapability.EXTERNAL_SIDE_EFFECT},
    }
    for index, (toolset, expected) in enumerate(cases.items()):
        name = f"future_{toolset}_{index}"
        reg.register(
            name=name,
            toolset=toolset,
            schema=_schema(name),
            handler=_handler,
        )
        assert expected <= reg.get_tool_capabilities(name)


def test_builtin_remote_mutation_tools_are_classified():
    # Import modules directly so the test does not depend on plugin discovery.
    import tools.feishu_drive_tool  # noqa: F401
    import tools.homeassistant_tool  # noqa: F401
    import tools.yuanbao_tools  # noqa: F401
    from tools.registry import registry

    for name in (
        "ha_call_service",
        "feishu_drive_reply_comment",
        "feishu_drive_add_comment",
        "yb_send_dm",
        "yb_send_sticker",
    ):
        assert ToolCapability.EXTERNAL_SIDE_EFFECT in registry.get_tool_capabilities(name), name

    # Read-only/query siblings stay available to safe-full.
    for name in (
        "ha_list_entities",
        "ha_get_state",
        "feishu_drive_list_comments",
        "feishu_drive_list_comment_replies",
        "yb_query_group_info",
        "yb_query_group_members",
        "yb_search_sticker",
    ):
        assert ToolCapability.EXTERNAL_SIDE_EFFECT not in registry.get_tool_capabilities(name), name


def test_external_side_effect_capability_is_mcp_unsafe():
    from agent.transports.hermes_tools_mcp_server import _MCP_UNSAFE_CAPABILITIES

    assert ToolCapability.EXTERNAL_SIDE_EFFECT in _MCP_UNSAFE_CAPABILITIES


def test_model_tools_plugin_discovery_guard_is_fail_closed(monkeypatch):
    import model_tools

    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "1")
    assert model_tools._plugin_discovery_enabled() is False

    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "true")
    assert model_tools._plugin_discovery_enabled() is False

    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "0")
    assert model_tools._plugin_discovery_enabled() is True


def test_model_tool_definition_cache_separates_exclusion_policy(monkeypatch):
    import model_tools

    model_tools._clear_tool_defs_cache()
    calls: list[frozenset[str]] = []

    def fake_compute(
        enabled_toolsets=None,
        disabled_toolsets=None,
        quiet_mode=False,
        skip_tool_search_assembly=False,
        excluded_capabilities=None,
    ):
        excluded = frozenset(excluded_capabilities or ())
        calls.append(excluded)
        return [
            {
                "type": "function",
                "function": {
                    "name": "probe_" + str(len(calls)),
                    "description": "probe",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    monkeypatch.setattr(model_tools, "_compute_tool_definitions", fake_compute)

    safe = model_tools.get_tool_definitions(
        enabled_toolsets=[],
        quiet_mode=True,
        skip_tool_search_assembly=True,
        excluded_capabilities={ToolCapability.HOST_EXECUTION},
    )
    trusted = model_tools.get_tool_definitions(
        enabled_toolsets=[],
        quiet_mode=True,
        skip_tool_search_assembly=True,
        excluded_capabilities=None,
    )

    assert safe[0]["function"]["name"] == "probe_1"
    assert trusted[0]["function"]["name"] == "probe_2"
    assert calls == [frozenset({ToolCapability.HOST_EXECUTION}), frozenset()]


def test_safe_full_build_requests_preprobe_exclusion(monkeypatch):
    import sys
    import types
    import agent.transports.hermes_tools_mcp_server as server_mod

    requested: list[object] = []

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            self.tools = []

        def add_tool(self, handler, *, name, description):
            self.tools.append(name)

    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

    def fake_get_tool_definitions(**kwargs):
        requested.append(kwargs.get("excluded_capabilities"))
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory",
                    "description": "memory",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    suppress_flags: list[bool] = []

    def fake_load_api(*, suppress_plugin_discovery: bool):
        suppress_flags.append(suppress_plugin_discovery)
        return fake_get_tool_definitions, (lambda name, args: "ok")

    monkeypatch.setattr(server_mod, "_load_model_tool_api", fake_load_api)
    monkeypatch.setattr(server_mod, "_discover_external_mcp_tools", lambda *a, **kw: None)
    monkeypatch.setattr(
        server_mod,
        "_load_hermes_tools_config",
        lambda: {
            "mode": "full",
            "discover_external": True,
            "allow_native_execution": False,
        },
    )

    built = server_mod._build_server()

    assert suppress_flags == [True]
    assert requested == [server_mod._MCP_UNSAFE_CAPABILITIES]
    assert built.tools == ["memory"]
