from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# tools/registry.py ---------------------------------------------------------
path = Path("tools/registry.py")
text = path.read_text()

text = replace_once(
    text,
    '    EXTERNAL_MCP = "external_mcp"\n',
    '    EXTERNAL_MCP = "external_mcp"\n    EXTERNAL_SIDE_EFFECT = "external_side_effect"\n    MCP_SAFE = "mcp_safe"\n',
    "capability constants",
)

old = '''_TOOLSET_DEFAULT_CAPABILITIES: Dict[str, frozenset[str]] = {
    "terminal": frozenset(
        {ToolCapability.HOST_EXECUTION, ToolCapability.PROCESS_CONTROL}
    ),
    "file": frozenset({ToolCapability.FILESYSTEM_ACCESS}),
    "code_execution": frozenset({ToolCapability.HOST_EXECUTION}),
    "computer_use": frozenset(
        {ToolCapability.UI_AUTOMATION, ToolCapability.HOST_EXECUTION}
    ),
    "delegation": frozenset({ToolCapability.SPAWN_AGENT}),
    "cronjob": frozenset({ToolCapability.SPAWN_AGENT}),
}
'''
new = '''_TOOLSET_DEFAULT_CAPABILITIES: Dict[str, frozenset[str]] = {
    "terminal": frozenset(
        {ToolCapability.HOST_EXECUTION, ToolCapability.PROCESS_CONTROL}
    ),
    "file": frozenset({ToolCapability.FILESYSTEM_ACCESS}),
    "code_execution": frozenset({ToolCapability.HOST_EXECUTION}),
    "computer_use": frozenset(
        {ToolCapability.UI_AUTOMATION, ToolCapability.HOST_EXECUTION}
    ),
    "delegation": frozenset({ToolCapability.SPAWN_AGENT}),
    "cronjob": frozenset({ToolCapability.SPAWN_AGENT}),
    "browser": frozenset(
        {
            ToolCapability.UI_AUTOMATION,
            ToolCapability.PROCESS_CONTROL,
            ToolCapability.HOST_EXECUTION,
        }
    ),
    "browser-cdp": frozenset(
        {
            ToolCapability.UI_AUTOMATION,
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
        }
    ),
    "vision": frozenset(
        {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.PROCESS_CONTROL}
    ),
    "video": frozenset(
        {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.PROCESS_CONTROL}
    ),
    "image_gen": frozenset({ToolCapability.FILESYSTEM_ACCESS}),
    "video_gen": frozenset(
        {ToolCapability.HOST_EXECUTION, ToolCapability.EXTERNAL_SIDE_EFFECT}
    ),
    "tts": frozenset(
        {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        }
    ),
}

# Safe-full is intentionally fail-closed. Only names carrying MCP_SAFE are
# eligible when allow_native_execution=false. New tools therefore stay hidden
# until their behavior has been reviewed explicitly.
_TOOL_DEFAULT_CAPABILITIES: Dict[str, frozenset[str]] = {
    "memory": frozenset({ToolCapability.MCP_SAFE}),
    "session_search": frozenset({ToolCapability.MCP_SAFE}),
    "todo": frozenset({ToolCapability.MCP_SAFE}),
    "web_search": frozenset({ToolCapability.MCP_SAFE}),
    "web_extract": frozenset({ToolCapability.MCP_SAFE}),
    "skills_list": frozenset({ToolCapability.MCP_SAFE}),
    "skill_view": frozenset({ToolCapability.MCP_SAFE}),
    "skill_manage": frozenset(
        {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        }
    ),
    "kanban_create": frozenset({ToolCapability.SPAWN_WORKER}),
    "kanban_unblock": frozenset({ToolCapability.SPAWN_WORKER}),
    "kanban_complete": frozenset({ToolCapability.SPAWN_WORKER}),
    "kanban_block": frozenset({ToolCapability.SPAWN_WORKER}),
}
'''
text = replace_once(text, old, new, "toolset defaults")

old = '''        resolved_capabilities = frozenset(
            _TOOLSET_DEFAULT_CAPABILITIES.get(toolset, frozenset())
        ).union(capabilities or ())
'''
new = '''        resolved_capabilities = (
            frozenset(_TOOLSET_DEFAULT_CAPABILITIES.get(toolset, frozenset()))
            .union(_TOOL_DEFAULT_CAPABILITIES.get(name, frozenset()))
            .union(capabilities or ())
        )
'''
text = replace_once(text, old, new, "resolved capabilities")

old = '    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:\n'
new = '''    def get_definitions(
        self,
        tool_names: Set[str],
        quiet: bool = False,
        exclude_capabilities: Optional[Set[str]] = None,
        require_capabilities: Optional[Set[str]] = None,
    ) -> List[dict]:
'''
text = replace_once(text, old, new, "get_definitions signature")

old = '''            entry = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
'''
new = '''            entry = entries_by_name.get(name)
            if not entry:
                continue
            # Filter security policy BEFORE availability checks. Some check_fn
            # implementations start Docker/browser processes or discover plugins;
            # a hidden unsafe tool must not execute code merely to decide whether
            # it would have been available.
            if exclude_capabilities and entry.capabilities.intersection(
                exclude_capabilities
            ):
                continue
            if require_capabilities and not frozenset(require_capabilities).issubset(
                entry.capabilities
            ):
                continue
            if entry.check_fn:
'''
text = replace_once(text, old, new, "pre-probe capability filter")
path.write_text(text)


# model_tools.py ------------------------------------------------------------
path = Path("model_tools.py")
text = path.read_text()
text = replace_once(
    text,
    'from typing import Dict, Any, List, Optional, Tuple\n',
    'from typing import Dict, Any, List, Optional, Set, Tuple\n',
    "typing Set",
)

old = '''# Plugin tool discovery (user/project/pip plugins)
try:
    from hermes_cli.plugins import discover_plugins
    discover_plugins()
except Exception as e:
    logger.debug("Plugin discovery failed: %s", e)
'''
new = '''# Plugin tool discovery (user/project/pip plugins). Security-sensitive
# transports can suppress this before importing model_tools: importing plugin
# modules is arbitrary Python execution even if their tools are filtered later.
if not os.environ.get("HERMES_SKIP_PLUGIN_DISCOVERY"):
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
    except Exception as e:
        logger.debug("Plugin discovery failed: %s", e)
'''
text = replace_once(text, old, new, "plugin discovery guard")

old = '''def get_tool_definitions(
    enabled_toolsets: Optional[List[str]] = None,
    disabled_toolsets: Optional[List[str]] = None,
    quiet_mode: bool = False,
    skip_tool_search_assembly: bool = False,
) -> List[Dict[str, Any]]:
'''
new = '''def get_tool_definitions(
    enabled_toolsets: Optional[List[str]] = None,
    disabled_toolsets: Optional[List[str]] = None,
    quiet_mode: bool = False,
    skip_tool_search_assembly: bool = False,
    exclude_capabilities: Optional[Set[str]] = None,
    require_capabilities: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
'''
text = replace_once(text, old, new, "get_tool_definitions signature")

old = '''            bool(skip_tool_search_assembly),
            _is_delegated_child_context(),
        )
'''
new = '''            bool(skip_tool_search_assembly),
            frozenset(exclude_capabilities or ()),
            frozenset(require_capabilities or ()),
            _is_delegated_child_context(),
        )
'''
text = replace_once(text, old, new, "tool defs cache key")

old = '''    result = _compute_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode,
                                       skip_tool_search_assembly=skip_tool_search_assembly)
'''
new = '''    result = _compute_tool_definitions(
        enabled_toolsets,
        disabled_toolsets,
        quiet_mode,
        skip_tool_search_assembly=skip_tool_search_assembly,
        exclude_capabilities=exclude_capabilities,
        require_capabilities=require_capabilities,
    )
'''
text = replace_once(text, old, new, "compute call")

old = '''def _compute_tool_definitions(
    enabled_toolsets: Optional[List[str]] = None,
    disabled_toolsets: Optional[List[str]] = None,
    quiet_mode: bool = False,
    skip_tool_search_assembly: bool = False,
) -> List[Dict[str, Any]]:
'''
new = '''def _compute_tool_definitions(
    enabled_toolsets: Optional[List[str]] = None,
    disabled_toolsets: Optional[List[str]] = None,
    quiet_mode: bool = False,
    skip_tool_search_assembly: bool = False,
    exclude_capabilities: Optional[Set[str]] = None,
    require_capabilities: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
'''
text = replace_once(text, old, new, "compute signature")

old = '    filtered_tools = registry.get_definitions(tools_to_include, quiet=quiet_mode)\n'
new = '''    filtered_tools = registry.get_definitions(
        tools_to_include,
        quiet=quiet_mode,
        exclude_capabilities=exclude_capabilities,
        require_capabilities=require_capabilities,
    )
'''
text = replace_once(text, old, new, "registry definitions call")
path.write_text(text)


# hermes_tools_mcp_server.py ------------------------------------------------
path = Path("agent/transports/hermes_tools_mcp_server.py")
text = path.read_text()

text = replace_once(
    text,
    '        ToolCapability.EXTERNAL_MCP,\n',
    '        ToolCapability.EXTERNAL_MCP,\n        ToolCapability.EXTERNAL_SIDE_EFFECT,\n',
    "unsafe external side effect",
)

old = '''    if resolved_mode == MCP_MODE_FULL:
        if allow_native_execution:
            return tuple(sorted(all_defs))
        caps = capabilities_by_name or {}
        return tuple(
            sorted(
                name
                for name in all_defs
                if not (_MCP_UNSAFE_CAPABILITIES & frozenset(caps.get(name, ())))
            )
        )
    return EXPOSED_TOOLS
'''
new = '''    caps = capabilities_by_name or {}
    if resolved_mode == MCP_MODE_FULL:
        if allow_native_execution:
            return tuple(sorted(all_defs))
        return tuple(
            sorted(
                name
                for name in all_defs
                if ToolCapability.MCP_SAFE in frozenset(caps.get(name, ()))
                and not (_MCP_UNSAFE_CAPABILITIES & frozenset(caps.get(name, ())))
            )
        )
    if allow_native_execution:
        return tuple(name for name in EXPOSED_TOOLS if name in all_defs)
    return tuple(
        name
        for name in EXPOSED_TOOLS
        if name in all_defs
        and not (_MCP_UNSAFE_CAPABILITIES & frozenset(caps.get(name, ())))
    )
'''
text = replace_once(text, old, new, "exposure policy")

old = '''    from model_tools import get_tool_definitions, handle_function_call

    mcp_config = _load_hermes_tools_config()
    mode = _resolve_mcp_mode(config=mcp_config)
    discover_external = _resolve_discover_external(config=mcp_config)
    allow_native_execution = _resolve_allow_native_execution(config=mcp_config)
'''
new = '''    mcp_config = _load_hermes_tools_config()
    mode = _resolve_mcp_mode(config=mcp_config)
    discover_external = _resolve_discover_external(config=mcp_config)
    allow_native_execution = _resolve_allow_native_execution(config=mcp_config)

    # Importing user/project/pip plugins executes arbitrary Python. Safe MCP
    # modes suppress plugin discovery before model_tools is imported; trusted
    # native mode intentionally retains the complete available plugin surface.
    if allow_native_execution:
        os.environ.pop("HERMES_SKIP_PLUGIN_DISCOVERY", None)
    else:
        os.environ["HERMES_SKIP_PLUGIN_DISCOVERY"] = "1"

    from model_tools import get_tool_definitions, handle_function_call
'''
text = replace_once(text, old, new, "model_tools import ordering")

old = '''            get_tool_definitions(
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
'''
new = '''            get_tool_definitions(
                quiet_mode=True,
                skip_tool_search_assembly=True,
                exclude_capabilities=(
                    None if allow_native_execution else set(_MCP_UNSAFE_CAPABILITIES)
                ),
                require_capabilities=(
                    {ToolCapability.MCP_SAFE}
                    if mode == MCP_MODE_FULL and not allow_native_execution
                    else None
                ),
            )
'''
text = replace_once(text, old, new, "pre-probe MCP filter")
path.write_text(text)


# tests/agent/transports/test_hermes_tools_mcp_policy.py --------------------
path = Path("tests/agent/transports/test_hermes_tools_mcp_policy.py")
text = path.read_text()
append = r'''


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
'''
if "test_safe_full_is_explicit_allow_and_fail_closed_for_unclassified_tools" not in text:
    text += append
path.write_text(text)
