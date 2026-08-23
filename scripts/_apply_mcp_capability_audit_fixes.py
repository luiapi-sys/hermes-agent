from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tools/registry.py",
    '''    # TTS can write arbitrary output paths and providers may launch ffmpeg,
    # local engines, or user-configured command providers.
    "tts": frozenset(
        {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        }
    ),
    # Remote integration toolsets are fail-closed as a unit. Some of them
''',
    '''    # Raw CDP is the browser escape hatch: it can navigate, evaluate JS,
    # mutate cookies/storage/network state, and drive a local or remote browser.
    "browser-cdp": frozenset(
        {
            ToolCapability.UI_AUTOMATION,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        }
    ),
    # TTS can write arbitrary output paths and providers may launch ffmpeg,
    # local engines, or user-configured command providers.
    "tts": frozenset(
        {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        }
    ),
    # Generation backends create remote artifacts and may materialize outputs
    # into the local Hermes filesystem. They are not read-only network tools.
    "image_gen": frozenset(
        {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.EXTERNAL_SIDE_EFFECT}
    ),
    "video_gen": frozenset(
        {ToolCapability.FILESYSTEM_ACCESS, ToolCapability.EXTERNAL_SIDE_EFFECT}
    ),
    # Skills and Projects are backed by local persistent files/SQLite. Even
    # their list/view operations read local user state, so safe-full treats the
    # whole toolset consistently with read_file instead of allowing a sibling
    # filesystem bypass through higher-level abstractions.
    "skills": frozenset({ToolCapability.FILESYSTEM_ACCESS}),
    "project": frozenset({ToolCapability.FILESYSTEM_ACCESS}),
    # Remote integration toolsets are fail-closed as a unit. Some of them
''',
)

replace_once(
    "tests/agent/transports/test_mcp_preexecution_boundary.py",
    '''        "tts": {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        },
        "discord": {ToolCapability.EXTERNAL_SIDE_EFFECT},
''',
    '''        "browser-cdp": {
            ToolCapability.UI_AUTOMATION,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        },
        "tts": {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.HOST_EXECUTION,
            ToolCapability.PROCESS_CONTROL,
        },
        "image_gen": {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.EXTERNAL_SIDE_EFFECT,
        },
        "video_gen": {
            ToolCapability.FILESYSTEM_ACCESS,
            ToolCapability.EXTERNAL_SIDE_EFFECT,
        },
        "skills": {ToolCapability.FILESYSTEM_ACCESS},
        "project": {ToolCapability.FILESYSTEM_ACCESS},
        "discord": {ToolCapability.EXTERNAL_SIDE_EFFECT},
''',
)

print("Capability audit patch applied")
