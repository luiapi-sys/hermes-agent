"""Tests for the hermes-tools-as-MCP server module surface."""

from __future__ import annotations

import inspect

from agent.transports.hermes_tools_mcp_server import (
    EXPOSED_TOOLS,
    MCP_ALLOW_NATIVE_EXECUTION_ENV,
    MCP_DISCOVER_EXTERNAL_ENV,
    MCP_MODE_CURATED,
    MCP_MODE_FULL,
    _NATIVE_BOUNDARY_TOOLS,
    _discover_external_mcp_tools,
    _env_bool,
    _load_hermes_tools_config,
    _resolve_allow_native_execution,
    _resolve_discover_external,
    _resolve_exposed_tool_names,
    _resolve_mcp_mode,
    _signature_from_schema,
)


class TestSignatureFromSchema:
    def test_simple_required_string_param(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        sig, annots = _signature_from_schema(schema)

        assert len(sig.parameters) == 1
        param = sig.parameters["query"]
        assert param.name == "query"
        assert param.kind == inspect.Parameter.KEYWORD_ONLY
        assert annots["query"] == str
        assert param.default is inspect.Parameter.empty

    def test_optional_integer_param(self):
        schema = {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        }
        sig, _ = _signature_from_schema(schema)
        assert sig.parameters["limit"].default is None

    def test_multiple_params_mixed_required_optional(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["query"],
        }
        sig, annots = _signature_from_schema(schema)

        assert len(sig.parameters) == 3
        assert annots["query"] == str
        assert sig.parameters["query"].default is inspect.Parameter.empty
        assert sig.parameters["limit"].default is None
        assert sig.parameters["offset"].default is None

    def test_skip_private_params(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "_internal": {"type": "string"},
            },
            "required": ["query", "_internal"],
        }
        sig, annots = _signature_from_schema(schema)

        assert "_internal" not in sig.parameters
        assert "_internal" not in annots
        assert "query" in sig.parameters

    def test_all_json_types(self):
        schema = {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "i": {"type": "integer"},
                "n": {"type": "number"},
                "b": {"type": "boolean"},
                "a": {"type": "array"},
                "o": {"type": "object"},
            },
            "required": ["s", "i", "n", "b", "a", "o"],
        }
        _, annots = _signature_from_schema(schema)

        assert annots["s"] == str
        assert annots["i"] == int
        assert annots["n"] == float
        assert annots["b"] == bool
        assert annots["a"] == list
        assert annots["o"] == dict

    def test_empty_schema(self):
        sig, annots = _signature_from_schema(None)
        assert len(sig.parameters) == 0
        assert len(annots) == 0

    def test_return_annotation_is_str(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }
        sig, _ = _signature_from_schema(schema)
        assert sig.return_annotation == str


class TestConfigPolicy:
    def test_loads_profile_aware_config_block(self, monkeypatch):
        import hermes_cli.config as config_module

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

        assert _load_hermes_tools_config() == {
            "mode": "full",
            "discover_external": False,
            "allow_native_execution": True,
        }

    def test_missing_or_invalid_config_block_is_safe(self, monkeypatch):
        import hermes_cli.config as config_module

        monkeypatch.setattr(config_module, "load_config", lambda: {"mcp": "bad"})
        assert _load_hermes_tools_config() == {}

    def test_discover_external_from_config(self, monkeypatch):
        monkeypatch.delenv(MCP_DISCOVER_EXTERNAL_ENV, raising=False)
        assert _resolve_discover_external(config={"discover_external": False}) is False
        assert _resolve_discover_external(config={"discover_external": True}) is True

    def test_native_execution_defaults_false_and_can_be_enabled_by_config(self, monkeypatch):
        monkeypatch.delenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, raising=False)
        assert _resolve_allow_native_execution(config={}) is False
        assert (
            _resolve_allow_native_execution(config={"allow_native_execution": True})
            is True
        )

    def test_internal_env_override_still_supported(self, monkeypatch):
        monkeypatch.setenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, "1")
        assert _resolve_allow_native_execution(config={"allow_native_execution": False}) is True


class TestExposureMode:
    def test_default_mode_is_curated(self, monkeypatch):
        monkeypatch.delenv("HERMES_MCP_MODE", raising=False)
        assert _resolve_mcp_mode(config={}) == MCP_MODE_CURATED

    def test_full_mode_from_config(self, monkeypatch):
        monkeypatch.delenv("HERMES_MCP_MODE", raising=False)
        assert _resolve_mcp_mode(config={"mode": "full"}) == MCP_MODE_FULL

    def test_legacy_internal_environment_override_is_supported(self, monkeypatch):
        monkeypatch.setenv("HERMES_MCP_MODE", "full")
        assert _resolve_mcp_mode(config={"mode": "curated"}) == MCP_MODE_FULL

    def test_mode_is_case_and_whitespace_tolerant(self):
        assert _resolve_mcp_mode("  FULL  ") == MCP_MODE_FULL
        assert _resolve_mcp_mode(" Curated ") == MCP_MODE_CURATED

    def test_invalid_mode_fails_closed_to_curated(self):
        assert _resolve_mcp_mode("everything") == MCP_MODE_CURATED

    def test_curated_mode_uses_historical_allowlist(self):
        defs = {
            "web_search": {},
            "terminal": {},
            "delegate_task": {},
        }
        assert _resolve_exposed_tool_names(defs, mode="curated") == EXPOSED_TOOLS

    def test_full_mode_hides_native_boundary_tools_by_default(self):
        defs = {
            "web_search": {},
            "terminal": {},
            "read_file": {},
            "write_file": {},
            "patch": {},
            "process": {},
            "execute_code": {},
            "delegate_task": {},
            "memory": {},
            "session_search": {},
            "todo": {},
            "plugin_custom_tool": {},
            "external_mcp_tool": {},
        }
        expected = tuple(sorted(set(defs) - _NATIVE_BOUNDARY_TOOLS))
        assert _resolve_exposed_tool_names(defs, mode="full") == expected

    def test_full_mode_can_explicitly_expose_complete_registry_surface(self):
        defs = {
            "web_search": {},
            "terminal": {},
            "read_file": {},
            "write_file": {},
            "patch": {},
            "process": {},
            "execute_code": {},
            "delegate_task": {},
            "memory": {},
            "session_search": {},
            "todo": {},
            "plugin_custom_tool": {},
            "external_mcp_tool": {},
        }
        assert _resolve_exposed_tool_names(
            defs,
            mode="full",
            allow_native_execution=True,
        ) == tuple(sorted(defs))

    def test_full_mode_is_dynamic_not_hardcoded(self):
        defs = {"future_tool_added_later": {}}
        assert _resolve_exposed_tool_names(defs, mode="full") == (
            "future_tool_added_later",
        )


class TestExternalDiscovery:
    def test_env_bool_accepts_common_values(self, monkeypatch):
        monkeypatch.setenv("X_BOOL", "yes")
        assert _env_bool("X_BOOL", False) is True
        monkeypatch.setenv("X_BOOL", "OFF")
        assert _env_bool("X_BOOL", True) is False

    def test_env_bool_invalid_value_uses_default(self, monkeypatch):
        monkeypatch.setenv("X_BOOL", "maybe")
        assert _env_bool("X_BOOL", True) is True
        assert _env_bool("X_BOOL", False) is False

    def test_curated_mode_never_discovers_external_mcp(self, monkeypatch):
        import hermes_cli.mcp_startup as startup

        calls = []
        monkeypatch.setattr(
            startup,
            "_discover_mcp_tools_without_interactive_oauth",
            lambda: calls.append("discover"),
        )

        _discover_external_mcp_tools(MCP_MODE_CURATED, enabled=True)
        assert calls == []

    def test_full_mode_discovers_external_mcp_before_snapshot(self, monkeypatch):
        import hermes_cli.mcp_startup as startup

        calls = []
        monkeypatch.setattr(
            startup,
            "_discover_mcp_tools_without_interactive_oauth",
            lambda: calls.append("discover"),
        )

        _discover_external_mcp_tools(MCP_MODE_FULL, enabled=True)
        assert calls == ["discover"]

    def test_full_mode_can_disable_external_discovery(self, monkeypatch):
        import hermes_cli.mcp_startup as startup

        calls = []
        monkeypatch.setattr(
            startup,
            "_discover_mcp_tools_without_interactive_oauth",
            lambda: calls.append("discover"),
        )

        _discover_external_mcp_tools(MCP_MODE_FULL, enabled=False)
        assert calls == []


class TestModuleSurface:
    def test_module_imports_clean(self):
        from agent.transports import hermes_tools_mcp_server as m

        assert callable(m.main)
        assert callable(m._build_server)
        assert isinstance(m.EXPOSED_TOOLS, tuple)
        assert len(m.EXPOSED_TOOLS) > 0

    def test_curated_tools_are_safe_subset(self):
        forbidden = {
            "terminal",
            "shell",
            "read_file",
            "write_file",
            "patch",
            "search_files",
            "process",
        }
        leaked = forbidden & set(EXPOSED_TOOLS)
        assert not leaked

    def test_expected_hermes_specific_tools_listed(self):
        for required in (
            "web_search",
            "web_extract",
            "browser_navigate",
            "vision_analyze",
            "image_generate",
            "skill_view",
        ):
            assert required in EXPOSED_TOOLS

    def test_agent_loop_tools_not_in_curated_allowlist(self):
        for agent_loop_tool in (
            "delegate_task",
            "memory",
            "session_search",
            "todo",
        ):
            assert agent_loop_tool not in EXPOSED_TOOLS

    def test_kanban_worker_tools_exposed_in_curated_mode(self):
        for worker_tool in (
            "kanban_complete",
            "kanban_block",
            "kanban_comment",
            "kanban_heartbeat",
        ):
            assert worker_tool in EXPOSED_TOOLS

    def test_kanban_orchestrator_tools_exposed_in_curated_mode(self):
        for orch_tool in (
            "kanban_create",
            "kanban_show",
            "kanban_list",
            "kanban_unblock",
            "kanban_link",
        ):
            assert worker_tool in EXPOSED_TOOLS


class TestBuildServer:
    def test_build_requests_raw_pre_tool_search_catalog(self, monkeypatch):
        """Full exposure must not be collapsed by progressive Tool Search."""
        import sys
        import types
        import agent.transports.hermes_tools_mcp_server as m

        calls = []

        class FakeFastMCP:
            def __init__(self, *args, **kwargs):
                self.tools = []

            def add_tool(self, handler, *, name, description):
                self.tools.append(name)

        fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
        fake_fastmcp.FastMCP = FakeFastMCP
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

        fake_model_tools = types.ModuleType("model_tools")

        def fake_get_tool_definitions(**kwargs):
            calls.append(kwargs)
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "description": "terminal",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]

        fake_model_tools.get_tool_definitions = fake_get_tool_definitions
        fake_model_tools.handle_function_call = lambda name, args: "ok"
        monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)
        monkeypatch.setattr(m, "_load_hermes_tools_config", lambda: {})
        monkeypatch.setenv("HERMES_MCP_MODE", "full")
        monkeypatch.setenv(MCP_DISCOVER_EXTERNAL_ENV, "0")
        monkeypatch.setenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, "1")

        server = m._build_server()

        assert server.tools == ["terminal"]
        assert calls == [
            {
                "quiet_mode": True,
                "skip_tool_search_assembly": True,
            }
        ]

    def test_full_mode_without_native_opt_in_does_not_register_terminal(self, monkeypatch):
        import sys
        import types
        import agent.transports.hermes_tools_mcp_server as m

        class FakeFastMCP:
            def __init__(self, *args, **kwargs):
                self.tools = []

            def add_tool(self, handler, *, name, description):
                self.tools.append(name)

        fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
        fake_fastmcp.FastMCP = FakeFastMCP
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

        fake_model_tools = types.ModuleType("model_tools")
        fake_model_tools.get_tool_definitions = lambda **kwargs: [
            {
                "type": "function",
                "function": {
                    "name": "terminal",
                    "description": "terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory",
                    "description": "memory",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
        fake_model_tools.handle_function_call = lambda name, args: "ok"
        monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)
        monkeypatch.setattr(m, "_load_hermes_tools_config", lambda: {"mode": "full"})
        monkeypatch.delenv("HERMES_MCP_MODE", raising=False)
        monkeypatch.delenv(MCP_ALLOW_NATIVE_EXECUTION_ENV, raising=False)
        monkeypatch.setenv(MCP_DISCOVER_EXTERNAL_ENV, "0")

        class FakeBridge:
            def __init__(self, available_tool_names):
                pass

            def supports(self, name):
                return False

        import agent.transports.hermes_tools_mcp_context as context_module

        monkeypatch.setattr(context_module, "MCPAgentContextBridge", FakeBridge)

        server = m._build_server()
        assert server.tools == ["memory"]


class TestMain:
    def test_main_returns_2_when_mcp_unavailable(self, monkeypatch):
        import agent.transports.hermes_tools_mcp_server as m

        def boom_build(*a, **kw):
            raise ImportError("mcp not installed")

        monkeypatch.setattr(m, "_build_server", boom_build)
        rc = m.main(["--verbose"])
        assert rc == 2

    def test_main_handles_keyboard_interrupt(self, monkeypatch):
        import agent.transports.hermes_tools_mcp_server as m

        class FakeServer:
            def run(self):
                raise KeyboardInterrupt()

        monkeypatch.setattr(m, "_build_server", lambda: FakeServer())
        rc = m.main([])
        assert rc == 0

    def test_main_returns_1_on_runtime_error(self, monkeypatch):
        import agent.transports.hermes_tools_mcp_server as m

        class CrashingServer:
            def run(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(m, "_build_server", lambda: CrashingServer())
        rc = m.main([])
        assert rc == 1
