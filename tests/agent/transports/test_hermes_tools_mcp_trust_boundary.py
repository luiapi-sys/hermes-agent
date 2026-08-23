from __future__ import annotations

from pathlib import Path

from tools.registry import ToolCapability, ToolRegistry


def _register_dummy(registry: ToolRegistry, *, name: str, toolset: str, check_fn=None, capabilities=None):
    registry.register(
        name=name,
        toolset=toolset,
        schema={"name": name, "description": name, "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kwargs: "ok",
        check_fn=check_fn,
        capabilities=capabilities,
    )


def test_unsafe_toolsets_inherit_trust_boundary_capabilities():
    registry = ToolRegistry()
    cases = {
        "browser": {ToolCapability.UI_AUTOMATION, ToolCapability.PROCESS_CONTROL, ToolCapability.FILESYSTEM_ACCESS},
        "browser-cdp": {ToolCapability.UI_AUTOMATION, ToolCapability.FILESYSTEM_ACCESS},
        "tts": {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.HOST_EXECUTION, ToolCapability.PROCESS_CONTROL},
        "vision": {ToolCapability.FILESYSTEM_ACCESS},
        "video": {ToolCapability.FILESYSTEM_ACCESS},
        "image_gen": {ToolCapability.FILESYSTEM_ACCESS},
    }
    for index, (toolset, expected) in enumerate(cases.items()):
        name = f"dummy_{index}"
        _register_dummy(registry, name=name, toolset=toolset)
        assert expected <= set(registry.get_tool_capabilities(name))


def test_capability_exclusion_happens_before_availability_probe():
    registry = ToolRegistry()
    calls = []

    def dangerous_probe():
        calls.append("ran")
        return True

    _register_dummy(
        registry,
        name="dangerous_probe_tool",
        toolset="custom",
        check_fn=dangerous_probe,
        capabilities={ToolCapability.PROCESS_CONTROL},
    )
    definitions = registry.get_definitions(
        {"dangerous_probe_tool"},
        quiet=True,
        excluded_capabilities={ToolCapability.PROCESS_CONTROL},
    )
    assert definitions == []
    assert calls == []


def test_mixed_toolset_mutators_are_explicitly_classified():
    # Import only the modules whose registrations are under test; handlers are
    # lazy and do not perform remote calls at import time.
    import tools.discord_tool  # noqa: F401
    import tools.feishu_drive_tool  # noqa: F401
    import tools.homeassistant_tool  # noqa: F401
    import tools.kanban_tools  # noqa: F401
    import tools.skill_manager_tool  # noqa: F401
    import tools.yuanbao_tools  # noqa: F401
    from tools.registry import registry

    expected = {
        "skill_manage": {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.HOST_EXECUTION},
        "ha_call_service": {ToolCapability.REMOTE_MUTATION},
        "discord": {ToolCapability.REMOTE_MUTATION},
        "discord_admin": {ToolCapability.REMOTE_MUTATION},
        "feishu_drive_reply_comment": {ToolCapability.REMOTE_MUTATION},
        "feishu_drive_add_comment": {ToolCapability.REMOTE_MUTATION},
        "yb_send_dm": {ToolCapability.REMOTE_MUTATION, ToolCapability.FILESYSTEM_ACCESS},
        "yb_send_sticker": {ToolCapability.REMOTE_MUTATION},
        "kanban_block": {ToolCapability.SPAWN_WORKER},
        "kanban_heartbeat": {ToolCapability.SPAWN_WORKER, ToolCapability.PROCESS_CONTROL},
        "kanban_comment": {ToolCapability.SPAWN_WORKER},
        "kanban_attach": {ToolCapability.FILESYSTEM_ACCESS},
        "kanban_attach_url": {ToolCapability.FILESYSTEM_ACCESS},
        "kanban_link": {ToolCapability.SPAWN_WORKER},
    }
    for name, required in expected.items():
        assert required <= set(registry.get_tool_capabilities(name)), name


def test_read_only_service_tools_are_not_blanket_classified_as_remote_mutations():
    import tools.feishu_drive_tool  # noqa: F401
    import tools.homeassistant_tool  # noqa: F401
    from tools.registry import registry

    for name in (
        "ha_list_entities",
        "ha_get_state",
        "ha_list_services",
        "feishu_drive_list_comments",
        "feishu_drive_list_comment_replies",
    ):
        assert ToolCapability.REMOTE_MUTATION not in registry.get_tool_capabilities(name), name


def test_trusted_policy_clears_safe_plugin_discovery_suppression():
    source = Path("agent/transports/hermes_tools_mcp_server.py").read_text()
    assert 'os.environ.pop("HERMES_SKIP_PLUGIN_DISCOVERY", None)' in source
    assert "if allow_native_execution:\n        try:\n            from hermes_cli.plugins import discover_plugins" in source
