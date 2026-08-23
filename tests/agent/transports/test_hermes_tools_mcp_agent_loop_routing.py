from __future__ import annotations

import sys
import types


def test_full_mode_routes_agent_loop_tool_through_context_bridge(monkeypatch):
    import agent.transports.hermes_tools_mcp_context as context_mod
    import agent.transports.hermes_tools_mcp_server as server_mod

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            self.handlers = {}

        def add_tool(self, handler, *, name, description):
            self.handlers[name] = handler

    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

    direct_calls = []
    fake_model_tools = types.ModuleType("model_tools")
    fake_model_tools.get_tool_definitions = lambda **kwargs: [
        {
            "type": "function",
            "function": {
                "name": "todo",
                "description": "todo",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "terminal",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    fake_model_tools.handle_function_call = lambda name, args: (
        direct_calls.append((name, args)) or f"direct:{name}"
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    bridged_calls = []

    class FakeBridge:
        def __init__(self, *, available_tool_names=()):
            assert set(available_tool_names) == {"todo", "terminal"}

        @staticmethod
        def supports(name):
            return name == "todo"

        def dispatch(self, name, args):
            bridged_calls.append((name, args))
            return f"bridged:{name}"

    monkeypatch.setattr(context_mod, "MCPAgentContextBridge", FakeBridge)
    monkeypatch.setenv("HERMES_MCP_MODE", "full")
    monkeypatch.setenv("HERMES_MCP_DISCOVER_EXTERNAL", "0")

    server = server_mod._build_server()

    assert server.handlers["todo"]() == "bridged:todo"
    assert bridged_calls == [("todo", {})]
    assert direct_calls == []

    assert server.handlers["terminal"]() == "direct:terminal"
    assert direct_calls == [("terminal", {})]


def test_curated_mode_does_not_initialize_agent_context_bridge(monkeypatch):
    import agent.transports.hermes_tools_mcp_context as context_mod
    import agent.transports.hermes_tools_mcp_server as server_mod

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            self.handlers = {}

        def add_tool(self, handler, *, name, description):
            self.handlers[name] = handler

    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

    fake_model_tools = types.ModuleType("model_tools")
    fake_model_tools.get_tool_definitions = lambda **kwargs: [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "web search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    fake_model_tools.handle_function_call = lambda name, args: "direct"
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    class ExplodingBridge:
        def __init__(self, **kwargs):
            raise AssertionError("curated mode must not initialize context bridge")

    monkeypatch.setattr(context_mod, "MCPAgentContextBridge", ExplodingBridge)
    monkeypatch.setenv("HERMES_MCP_MODE", "curated")

    server = server_mod._build_server()
    assert server.handlers["web_search"]() == "direct"
