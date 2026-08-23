from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Record the policy state used on the FIRST model_tools import. Reading the
# environment later is insufficient because importing plugins is irreversible
# process state.
replace_once(
    "model_tools.py",
    '''def _plugin_discovery_enabled() -> bool:
    """Return False only for the dedicated fail-closed MCP import path.

    This environment switch is intentionally narrow: normal CLI/gateway/ACP
    processes keep historical plugin discovery. The MCP transport sets it
    only while importing ``model_tools`` for safe-full mode so user/project/
    pip plugin code cannot execute before the transport policy is established.
    """
    raw = os.environ.get("HERMES_SKIP_PLUGIN_DISCOVERY", "")
    return str(raw).strip().lower() not in {"1", "true", "yes", "on"}


discover_builtin_tools()
''',
    '''def _plugin_discovery_enabled() -> bool:
    """Return False only for the dedicated fail-closed MCP import path.

    This environment switch is intentionally narrow: normal CLI/gateway/ACP
    processes keep historical plugin discovery. The MCP transport sets it
    only while importing ``model_tools`` for safe-full mode so user/project/
    pip plugin code cannot execute before the transport policy is established.
    """
    raw = os.environ.get("HERMES_SKIP_PLUGIN_DISCOVERY", "")
    return str(raw).strip().lower() not in {"1", "true", "yes", "on"}


# Immutable evidence of how this module's one-time discovery phase ran. A safe
# MCP transport must never trust the current environment alone when model_tools
# is already cached: plugin import side effects from an earlier permissive import
# cannot be undone.
_PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT = not _plugin_discovery_enabled()


discover_builtin_tools()
''',
)

replace_once(
    "model_tools.py",
    '''if _plugin_discovery_enabled():
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
    except Exception as e:
        logger.debug("Plugin discovery failed: %s", e)
else:
    logger.info("Plugin discovery suppressed by MCP safe-full import policy")
''',
    '''if not _PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT:
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
    except Exception as e:
        logger.debug("Plugin discovery failed: %s", e)
else:
    logger.info("Plugin discovery suppressed by MCP safe-full import policy")
''',
)

replace_once(
    "agent/transports/hermes_tools_mcp_server.py",
    '''    key = "HERMES_SKIP_PLUGIN_DISCOVERY"
    previous = os.environ.get(key)
    if suppress_plugin_discovery:
        os.environ[key] = "1"
    try:
        import importlib

        model_tools = importlib.import_module("model_tools")
        return model_tools.get_tool_definitions, model_tools.handle_function_call
    finally:
''',
    '''    key = "HERMES_SKIP_PLUGIN_DISCOVERY"
    previous = os.environ.get(key)

    # Importing plugin code is irreversible process state. If another import path
    # already initialized model_tools permissively, safe-full cannot retroactively
    # establish its pre-plugin boundary; reject startup rather than advertise a
    # safety posture the process no longer satisfies.
    existing = sys.modules.get("model_tools")
    if (
        suppress_plugin_discovery
        and existing is not None
        and not getattr(existing, "_PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT", False)
    ):
        raise RuntimeError(
            "safe-full MCP cannot establish the plugin execution boundary: "
            "model_tools was already imported with plugin discovery enabled"
        )

    if suppress_plugin_discovery:
        os.environ[key] = "1"
    try:
        import importlib

        model_tools = importlib.import_module("model_tools")
        if suppress_plugin_discovery and not getattr(
            model_tools, "_PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT", False
        ):
            raise RuntimeError(
                "safe-full MCP refused model_tools because plugin discovery "
                "was not suppressed at first import"
            )
        return model_tools.get_tool_definitions, model_tools.handle_function_call
    finally:
''',
)

# Add unit-level import-state invariants before the build-server tests.
replace_once(
    "tests/agent/transports/test_mcp_preexecution_boundary.py",
    '''def test_safe_full_build_resolves_policy_before_model_tools_import(monkeypatch):
''',
    '''def test_safe_model_api_import_rejects_prior_permissive_model_tools(monkeypatch):
    import sys
    import types
    import pytest
    import agent.transports.hermes_tools_mcp_server as server_mod

    fake = types.ModuleType("model_tools")
    fake._PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT = False
    monkeypatch.setitem(sys.modules, "model_tools", fake)

    with pytest.raises(RuntimeError, match="already imported with plugin discovery enabled"):
        server_mod._load_model_tool_api(suppress_plugin_discovery=True)


def test_safe_model_api_import_accepts_prior_suppressed_model_tools(monkeypatch):
    import sys
    import types
    import agent.transports.hermes_tools_mcp_server as server_mod

    fake = types.ModuleType("model_tools")
    fake._PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT = True
    fake.get_tool_definitions = lambda **kwargs: []
    fake.handle_function_call = lambda name, args: "ok"
    monkeypatch.setitem(sys.modules, "model_tools", fake)

    get_defs, handle = server_mod._load_model_tool_api(suppress_plugin_discovery=True)
    assert get_defs() == []
    assert handle("x", {}) == "ok"


def test_trusted_model_api_import_accepts_prior_permissive_model_tools(monkeypatch):
    import sys
    import types
    import agent.transports.hermes_tools_mcp_server as server_mod

    fake = types.ModuleType("model_tools")
    fake._PLUGIN_DISCOVERY_SUPPRESSED_AT_IMPORT = False
    fake.get_tool_definitions = lambda **kwargs: []
    fake.handle_function_call = lambda name, args: "ok"
    monkeypatch.setitem(sys.modules, "model_tools", fake)

    get_defs, handle = server_mod._load_model_tool_api(suppress_plugin_discovery=False)
    assert get_defs() == []
    assert handle("x", {}) == "ok"


def test_safe_full_build_resolves_policy_before_model_tools_import(monkeypatch):
''',
)

print("MCP import-state guard patch applied")
