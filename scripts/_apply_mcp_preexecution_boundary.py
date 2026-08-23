from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# tools/registry.py — classify unsafe capability classes centrally and make
# capability exclusion happen BEFORE availability check_fn probes.
# ---------------------------------------------------------------------------
replace_once(
    "tools/registry.py",
    '    SPAWN_WORKER = "spawn_worker"\n    EXTERNAL_MCP = "external_mcp"\n',
    '    SPAWN_WORKER = "spawn_worker"\n    EXTERNAL_MCP = "external_mcp"\n'
    '    EXTERNAL_SIDE_EFFECT = "external_side_effect"\n',
)

replace_once(
    "tools/registry.py",
    '    "computer_use": frozenset(\n'
    '        {ToolCapability.UI_AUTOMATION, ToolCapability.HOST_EXECUTION}\n'
    '    ),\n'
    '    "delegation": frozenset({ToolCapability.SPAWN_AGENT}),\n',
    '    "computer_use": frozenset(\n'
    '        {ToolCapability.UI_AUTOMATION, ToolCapability.HOST_EXECUTION}\n'
    '    ),\n'
    '    # Browser commands can launch/control local Chromium or a helper CLI.\n'
    '    "browser": frozenset(\n'
    '        {\n'
    '            ToolCapability.UI_AUTOMATION,\n'
    '            ToolCapability.HOST_EXECUTION,\n'
    '            ToolCapability.PROCESS_CONTROL,\n'
    '        }\n'
    '    ),\n'
    '    # TTS can write arbitrary output paths and providers may launch ffmpeg,\n'
    '    # local engines, or user-configured command providers.\n'
    '    "tts": frozenset(\n'
    '        {\n'
    '            ToolCapability.FILESYSTEM_ACCESS,\n'
    '            ToolCapability.HOST_EXECUTION,\n'
    '            ToolCapability.PROCESS_CONTROL,\n'
    '        }\n'
    '    ),\n'
    '    # Remote integration toolsets are fail-closed as a unit. Some of them\n'
    '    # multiplex reads and writes behind one schema/action enum, so trying to\n'
    '    # infer safety per call during static MCP registration is not sound.\n'
    '    "discord": frozenset({ToolCapability.EXTERNAL_SIDE_EFFECT}),\n'
    '    "discord_admin": frozenset({ToolCapability.EXTERNAL_SIDE_EFFECT}),\n'
    '    "homeassistant": frozenset({ToolCapability.EXTERNAL_SIDE_EFFECT}),\n'
    '    "feishu_drive": frozenset({ToolCapability.EXTERNAL_SIDE_EFFECT}),\n'
    '    "hermes-yuanbao": frozenset({ToolCapability.EXTERNAL_SIDE_EFFECT}),\n'
    '    "delegation": frozenset({ToolCapability.SPAWN_AGENT}),\n',
)

replace_once(
    "tools/registry.py",
    '    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:\n',
    '    def get_definitions(\n'
    '        self,\n'
    '        tool_names: Set[str],\n'
    '        quiet: bool = False,\n'
    '        excluded_capabilities: Set[str] | None = None,\n'
    '    ) -> List[dict]:\n',
)

replace_once(
    "tools/registry.py",
    '        result = []\n'
    '        # Per-call cache on top of the 30 s TTL — handles repeat probes of the\n',
    '        result = []\n'
    '        excluded = frozenset(excluded_capabilities or ())\n'
    '        # Per-call cache on top of the 30 s TTL — handles repeat probes of the\n',
)

replace_once(
    "tools/registry.py",
    '            if not entry:\n'
    '                continue\n'
    '            if entry.check_fn:\n',
    '            if not entry:\n'
    '                continue\n'
    '            # Security policy is evaluated before check_fn. Availability\n'
    '            # probes are executable code and may spawn subprocesses or touch\n'
    '            # external services, so a denied capability must never be probed.\n'
    '            if excluded and entry.capabilities & excluded:\n'
    '                if not quiet:\n'
    '                    logger.debug(\n'
    '                        "Tool %s excluded by capability policy: %s",\n'
    '                        name,\n'
    '                        ", ".join(sorted(entry.capabilities & excluded)),\n'
    '                    )\n'
    '                continue\n'
    '            if entry.check_fn:\n',
)

replace_once(
    "tools/registry.py",
    '        Only tools whose ``check_fn()`` returns True (or have no check_fn)\n'
    '        are included. ``check_fn()`` results are cached for ~30 s via\n',
    '        Tools carrying an ``excluded_capabilities`` value are removed before\n'
    '        their ``check_fn`` is evaluated. Remaining tools are included only\n'
    '        when ``check_fn()`` returns True (or have no check_fn). ``check_fn()``\n'
    '        results are cached for ~30 s via\n',
)


# ---------------------------------------------------------------------------
# model_tools.py — add an import-time plugin-discovery kill switch used only by
# the dedicated safe MCP process; thread capability exclusions through the
# definition cache and registry before probes execute.
# ---------------------------------------------------------------------------
replace_once(
    "model_tools.py",
    '# =============================================================================\n'
    '# Tool Discovery  (importing each module triggers its registry.register calls)\n'
    '# =============================================================================\n'
    '\n'
    'discover_builtin_tools()\n',
    '# =============================================================================\n'
    '# Tool Discovery  (importing each module triggers its registry.register calls)\n'
    '# =============================================================================\n'
    '\n'
    'def _plugin_discovery_enabled() -> bool:\n'
    '    """Return False only for the dedicated fail-closed MCP import path.\n'
    '\n'
    '    This environment switch is intentionally narrow: normal CLI/gateway/ACP\n'
    '    processes keep historical plugin discovery. The MCP transport sets it\n'
    '    only while importing ``model_tools`` for safe-full mode so user/project/\n'
    '    pip plugin code cannot execute before the transport policy is established.\n'
    '    """\n'
    '    raw = os.environ.get("HERMES_SKIP_PLUGIN_DISCOVERY", "")\n'
    '    return str(raw).strip().lower() not in {"1", "true", "yes", "on"}\n'
    '\n'
    '\n'
    'discover_builtin_tools()\n',
)

replace_once(
    "model_tools.py",
    '# Plugin tool discovery (user/project/pip plugins)\n'
    'try:\n'
    '    from hermes_cli.plugins import discover_plugins\n'
    '    discover_plugins()\n'
    'except Exception as e:\n'
    '    logger.debug("Plugin discovery failed: %s", e)\n',
    '# Plugin tool discovery (user/project/pip plugins). Safe-full MCP imports\n'
    '# this module with HERMES_SKIP_PLUGIN_DISCOVERY=1 so arbitrary plugin code\n'
    '# cannot execute before the MCP capability policy is applied.\n'
    'if _plugin_discovery_enabled():\n'
    '    try:\n'
    '        from hermes_cli.plugins import discover_plugins\n'
    '        discover_plugins()\n'
    '    except Exception as e:\n'
    '        logger.debug("Plugin discovery failed: %s", e)\n'
    'else:\n'
    '    logger.info("Plugin discovery suppressed by MCP safe-full import policy")\n',
)

replace_once(
    "model_tools.py",
    'def get_tool_definitions(\n'
    '    enabled_toolsets: Optional[List[str]] = None,\n'
    '    disabled_toolsets: Optional[List[str]] = None,\n'
    '    quiet_mode: bool = False,\n'
    '    skip_tool_search_assembly: bool = False,\n'
    ') -> List[Dict[str, Any]]:\n',
    'def get_tool_definitions(\n'
    '    enabled_toolsets: Optional[List[str]] = None,\n'
    '    disabled_toolsets: Optional[List[str]] = None,\n'
    '    quiet_mode: bool = False,\n'
    '    skip_tool_search_assembly: bool = False,\n'
    '    excluded_capabilities=None,\n'
    ') -> List[Dict[str, Any]]:\n',
)

replace_once(
    "model_tools.py",
    '        skip_tool_search_assembly: When True, return the pre-assembly tool list\n'
    '            (raw schemas for every enabled tool). Used internally by the\n'
    '            tool_search / tool_describe bridge handlers so they can read the\n'
    '            real catalog, not the already-collapsed one. Public callers should\n'
    '            leave this False.\n',
    '        skip_tool_search_assembly: When True, return the pre-assembly tool list\n'
    '            (raw schemas for every enabled tool). Used internally by the\n'
    '            tool_search / tool_describe bridge handlers so they can read the\n'
    '            real catalog, not the already-collapsed one. Public callers should\n'
    '            leave this False.\n'
    '        excluded_capabilities: Security capability classes to remove before\n'
    '            registry availability probes execute. Intended for transports\n'
    '            that must establish a fail-closed boundary before check_fn code.\n',
)

replace_once(
    "model_tools.py",
    '            bool(skip_tool_search_assembly),\n'
    '            _is_delegated_child_context(),\n',
    '            bool(skip_tool_search_assembly),\n'
    '            frozenset(excluded_capabilities or ()),\n'
    '            _is_delegated_child_context(),\n',
)

replace_once(
    "model_tools.py",
    '    result = _compute_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode,\n'
    '                                       skip_tool_search_assembly=skip_tool_search_assembly)\n',
    '    result = _compute_tool_definitions(\n'
    '        enabled_toolsets,\n'
    '        disabled_toolsets,\n'
    '        quiet_mode,\n'
    '        skip_tool_search_assembly=skip_tool_search_assembly,\n'
    '        excluded_capabilities=excluded_capabilities,\n'
    '    )\n',
)

replace_once(
    "model_tools.py",
    'def _compute_tool_definitions(\n'
    '    enabled_toolsets: Optional[List[str]] = None,\n'
    '    disabled_toolsets: Optional[List[str]] = None,\n'
    '    quiet_mode: bool = False,\n'
    '    skip_tool_search_assembly: bool = False,\n'
    ') -> List[Dict[str, Any]]:\n',
    'def _compute_tool_definitions(\n'
    '    enabled_toolsets: Optional[List[str]] = None,\n'
    '    disabled_toolsets: Optional[List[str]] = None,\n'
    '    quiet_mode: bool = False,\n'
    '    skip_tool_search_assembly: bool = False,\n'
    '    excluded_capabilities=None,\n'
    ') -> List[Dict[str, Any]]:\n',
)

replace_once(
    "model_tools.py",
    '    filtered_tools = registry.get_definitions(tools_to_include, quiet=quiet_mode)\n',
    '    filtered_tools = registry.get_definitions(\n'
    '        tools_to_include,\n'
    '        quiet=quiet_mode,\n'
    '        excluded_capabilities=excluded_capabilities,\n'
    '    )\n',
)


# ---------------------------------------------------------------------------
# MCP transport — resolve policy before model_tools import; safe-full imports
# with plugins suppressed and passes unsafe capabilities into pre-probe filter.
# ---------------------------------------------------------------------------
replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    '        ToolCapability.EXTERNAL_MCP,\n'
    '    }\n',
    '        ToolCapability.EXTERNAL_MCP,\n'
    '        ToolCapability.EXTERNAL_SIDE_EFFECT,\n'
    '    }\n',
)

insert_anchor = 'def _build_server() -> Any:\n'
loader = '''def _load_model_tool_api(*, suppress_plugin_discovery: bool):\n    """Import model_tools only after the MCP policy is known.\n\n    Safe-full temporarily sets the narrow model_tools import guard so plugin\n    discovery cannot execute user/project/pip plugin code before capability\n    filtering. The environment is restored immediately after import; the module\n    remains cached with plugin discovery skipped for this dedicated process.\n    """\n    key = "HERMES_SKIP_PLUGIN_DISCOVERY"\n    previous = os.environ.get(key)\n    if suppress_plugin_discovery:\n        os.environ[key] = "1"\n    try:\n        import importlib\n\n        model_tools = importlib.import_module("model_tools")\n        return model_tools.get_tool_definitions, model_tools.handle_function_call\n    finally:\n        if suppress_plugin_discovery:\n            if previous is None:\n                os.environ.pop(key, None)\n            else:\n                os.environ[key] = previous\n\n\n'''
replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    insert_anchor,
    loader + insert_anchor,
)

replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    '    from model_tools import get_tool_definitions, handle_function_call\n'
    '\n'
    '    mcp_config = _load_hermes_tools_config()\n'
    '    mode = _resolve_mcp_mode(config=mcp_config)\n'
    '    discover_external = _resolve_discover_external(config=mcp_config)\n'
    '    allow_native_execution = _resolve_allow_native_execution(config=mcp_config)\n',
    '    mcp_config = _load_hermes_tools_config()\n'
    '    mode = _resolve_mcp_mode(config=mcp_config)\n'
    '    discover_external = _resolve_discover_external(config=mcp_config)\n'
    '    allow_native_execution = _resolve_allow_native_execution(config=mcp_config)\n'
    '    safe_full = mode == MCP_MODE_FULL and not allow_native_execution\n'
    '\n'
    '    # Critical ordering: policy is resolved before model_tools import. In\n'
    '    # safe-full, plugin discovery is suppressed during that import so plugin\n'
    '    # executable code cannot run before the transport boundary exists.\n'
    '    get_tool_definitions, handle_function_call = _load_model_tool_api(\n'
    '        suppress_plugin_discovery=safe_full,\n'
    '    )\n',
)

replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    '            "registry tool allowed by the MCP policy. Stateful agent-loop tools "\n'
    '            "are supported through the MCP context bridge. Tools carrying native "\n'
    '            "execution, filesystem, process, UI-automation, or spawn capabilities "\n'
    '            "are included only when allow_native_execution is explicitly enabled."\n',
    '            "registry tool allowed by the MCP policy. Stateful agent-loop tools "\n'
    '            "are supported through the MCP context bridge. Tools carrying native "\n'
    '            "execution, filesystem, process, UI-automation, spawn, external-MCP, "\n'
    '            "or remote-side-effect capabilities are included only when "\n'
    '            "allow_native_execution is explicitly enabled."\n',
)

replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    '            get_tool_definitions(\n'
    '                quiet_mode=True,\n'
    '                skip_tool_search_assembly=True,\n'
    '            )\n',
    '            get_tool_definitions(\n'
    '                quiet_mode=True,\n'
    '                skip_tool_search_assembly=True,\n'
    '                excluded_capabilities=(\n'
    '                    _MCP_UNSAFE_CAPABILITIES if safe_full else None\n'
    '                ),\n'
    '            )\n',
)


# ---------------------------------------------------------------------------
# Replace the boundary regression suite so it matches the deliberately
# fail-closed integration-toolset policy (mixed read/write toolsets are gated
# as a unit in safe-full; trusted-full still exposes them all).
# ---------------------------------------------------------------------------
Path("tests/agent/transports/test_mcp_preexecution_boundary.py").write_text(
    '''"""Regression tests for MCP policy enforcement before executable discovery/probes."""\n\nfrom __future__ import annotations\n\nfrom tools.registry import ToolCapability, ToolRegistry\n\n\ndef _schema(name: str) -> dict:\n    return {\n        "name": name,\n        "description": name,\n        "parameters": {"type": "object", "properties": {}},\n    }\n\n\ndef _handler(args, **kwargs):\n    return "ok"\n\n\ndef test_registry_exclusion_skips_unsafe_availability_probe_entirely():\n    reg = ToolRegistry()\n    probes: list[str] = []\n\n    reg.register(\n        name="danger",\n        toolset="test-danger",\n        schema=_schema("danger"),\n        handler=_handler,\n        check_fn=lambda: probes.append("danger") or True,\n        capabilities={ToolCapability.HOST_EXECUTION},\n    )\n    reg.register(\n        name="safe",\n        toolset="test-safe",\n        schema=_schema("safe"),\n        handler=_handler,\n        check_fn=lambda: probes.append("safe") or True,\n    )\n\n    defs = reg.get_definitions(\n        {"danger", "safe"},\n        quiet=True,\n        excluded_capabilities={ToolCapability.HOST_EXECUTION},\n    )\n\n    assert [item["function"]["name"] for item in defs] == ["safe"]\n    assert probes == ["safe"]\n\n\ndef test_execution_and_remote_mutation_toolsets_inherit_fail_closed_capabilities():\n    reg = ToolRegistry()\n    cases = {\n        "browser": {\n            ToolCapability.UI_AUTOMATION,\n            ToolCapability.HOST_EXECUTION,\n            ToolCapability.PROCESS_CONTROL,\n        },\n        "tts": {\n            ToolCapability.FILESYSTEM_ACCESS,\n            ToolCapability.HOST_EXECUTION,\n            ToolCapability.PROCESS_CONTROL,\n        },\n        "discord": {ToolCapability.EXTERNAL_SIDE_EFFECT},\n        "discord_admin": {ToolCapability.EXTERNAL_SIDE_EFFECT},\n        "homeassistant": {ToolCapability.EXTERNAL_SIDE_EFFECT},\n        "feishu_drive": {ToolCapability.EXTERNAL_SIDE_EFFECT},\n        "hermes-yuanbao": {ToolCapability.EXTERNAL_SIDE_EFFECT},\n    }\n    for index, (toolset, expected) in enumerate(cases.items()):\n        name = f"future_{index}"\n        reg.register(name=name, toolset=toolset, schema=_schema(name), handler=_handler)\n        assert expected <= reg.get_tool_capabilities(name)\n\n\ndef test_external_side_effect_capability_is_mcp_unsafe():\n    from agent.transports.hermes_tools_mcp_server import _MCP_UNSAFE_CAPABILITIES\n\n    assert ToolCapability.EXTERNAL_SIDE_EFFECT in _MCP_UNSAFE_CAPABILITIES\n\n\ndef test_model_tools_plugin_discovery_guard_is_fail_closed(monkeypatch):\n    import model_tools\n\n    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "1")\n    assert model_tools._plugin_discovery_enabled() is False\n    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "true")\n    assert model_tools._plugin_discovery_enabled() is False\n    monkeypatch.setenv("HERMES_SKIP_PLUGIN_DISCOVERY", "0")\n    assert model_tools._plugin_discovery_enabled() is True\n\n\ndef test_model_tool_definition_cache_separates_exclusion_policy(monkeypatch):\n    import model_tools\n\n    model_tools._clear_tool_defs_cache()\n    calls: list[frozenset[str]] = []\n\n    def fake_compute(\n        enabled_toolsets=None,\n        disabled_toolsets=None,\n        quiet_mode=False,\n        skip_tool_search_assembly=False,\n        excluded_capabilities=None,\n    ):\n        excluded = frozenset(excluded_capabilities or ())\n        calls.append(excluded)\n        return [\n            {\n                "type": "function",\n                "function": {\n                    "name": "probe_" + str(len(calls)),\n                    "description": "probe",\n                    "parameters": {"type": "object", "properties": {}},\n                },\n            }\n        ]\n\n    monkeypatch.setattr(model_tools, "_compute_tool_definitions", fake_compute)\n\n    safe = model_tools.get_tool_definitions(\n        enabled_toolsets=[],\n        quiet_mode=True,\n        skip_tool_search_assembly=True,\n        excluded_capabilities={ToolCapability.HOST_EXECUTION},\n    )\n    trusted = model_tools.get_tool_definitions(\n        enabled_toolsets=[],\n        quiet_mode=True,\n        skip_tool_search_assembly=True,\n        excluded_capabilities=None,\n    )\n\n    assert safe[0]["function"]["name"] == "probe_1"\n    assert trusted[0]["function"]["name"] == "probe_2"\n    assert calls == [frozenset({ToolCapability.HOST_EXECUTION}), frozenset()]\n\n\ndef test_safe_full_build_resolves_policy_before_model_tools_import(monkeypatch):\n    import sys\n    import types\n    import agent.transports.hermes_tools_mcp_server as server_mod\n\n    requested: list[object] = []\n\n    class FakeFastMCP:\n        def __init__(self, *args, **kwargs):\n            self.tools = []\n\n        def add_tool(self, handler, *, name, description):\n            self.tools.append(name)\n\n    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")\n    fake_fastmcp.FastMCP = FakeFastMCP\n    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)\n\n    def fake_get_tool_definitions(**kwargs):\n        requested.append(kwargs.get("excluded_capabilities"))\n        return [\n            {\n                "type": "function",\n                "function": {\n                    "name": "memory",\n                    "description": "memory",\n                    "parameters": {"type": "object", "properties": {}},\n                },\n            }\n        ]\n\n    suppress_flags: list[bool] = []\n\n    def fake_load_api(*, suppress_plugin_discovery: bool):\n        suppress_flags.append(suppress_plugin_discovery)\n        return fake_get_tool_definitions, (lambda name, args: "ok")\n\n    monkeypatch.setattr(server_mod, "_load_model_tool_api", fake_load_api)\n    monkeypatch.setattr(server_mod, "_discover_external_mcp_tools", lambda *a, **kw: None)\n    monkeypatch.setattr(\n        server_mod,\n        "_load_hermes_tools_config",\n        lambda: {\n            "mode": "full",\n            "discover_external": True,\n            "allow_native_execution": False,\n        },\n    )\n\n    built = server_mod._build_server()\n\n    assert suppress_flags == [True]\n    assert requested == [server_mod._MCP_UNSAFE_CAPABILITIES]\n    assert built.tools == ["memory"]\n\n\ndef test_trusted_full_keeps_plugin_discovery_and_probe_filter_disabled(monkeypatch):\n    import sys\n    import types\n    import agent.transports.hermes_tools_mcp_server as server_mod\n\n    class FakeFastMCP:\n        def __init__(self, *args, **kwargs):\n            self.tools = []\n\n        def add_tool(self, handler, *, name, description):\n            self.tools.append(name)\n\n    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")\n    fake_fastmcp.FastMCP = FakeFastMCP\n    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)\n\n    seen = {}\n\n    def fake_defs(**kwargs):\n        seen["excluded"] = kwargs.get("excluded_capabilities")\n        return []\n\n    def fake_load_api(*, suppress_plugin_discovery: bool):\n        seen["suppress"] = suppress_plugin_discovery\n        return fake_defs, (lambda name, args: "ok")\n\n    monkeypatch.setattr(server_mod, "_load_model_tool_api", fake_load_api)\n    monkeypatch.setattr(server_mod, "_discover_external_mcp_tools", lambda *a, **kw: None)\n    monkeypatch.setattr(\n        server_mod,\n        "_load_hermes_tools_config",\n        lambda: {"mode": "full", "discover_external": True, "allow_native_execution": True},\n    )\n\n    server_mod._build_server()\n\n    assert seen == {"suppress": False, "excluded": None}\n''',
    encoding="utf-8",
)

print("MCP pre-execution boundary patch applied successfully")
