from pathlib import Path

path = Path("agent/transports/hermes_tools_mcp_server.py")
text = path.read_text(encoding="utf-8")
old = '''            get_tool_definitions(
                quiet_mode=True,
                skip_tool_search_assembly=True,
                excluded_capabilities=(
                    _MCP_UNSAFE_CAPABILITIES if safe_full else None
                ),
            )
'''
new = '''            (
                get_tool_definitions(
                    quiet_mode=True,
                    skip_tool_search_assembly=True,
                    excluded_capabilities=_MCP_UNSAFE_CAPABILITIES,
                )
                if safe_full
                else get_tool_definitions(
                    quiet_mode=True,
                    skip_tool_search_assembly=True,
                )
            )
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one trusted-call compatibility anchor, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
