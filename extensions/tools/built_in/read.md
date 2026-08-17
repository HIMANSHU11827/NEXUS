# Tools

NEXUS AI tool system — 31 tool directories discovered by `ToolRegistry` via per-tool metadata, with `BaseTool` handler classes providing runtime behavior.

**Version:** 2.0.0

## Structure
```
tools/
  <toolname>/
    <toolname>.jsnol     — JSON tool definition (schema + metadata + version)
    <toolname>.md        — Tool documentation
    read.md              — Directory docs
    scripts/<tool>.py    — Handler extending BaseTool with __version__
```

Stub tools (planned, not yet implemented) follow a reduced convention:
```
tools/<toolname>/
  <toolname>.json        — JSON metadata only (no .md, no executable handler)
```

## Registered Tools
| Tool | Status | Description |
|------|--------|-------------|
| `code_search` | Stable | Grep/glob code search with workspace containment |
| `creating` | Stable | Create new files |
| `deep_research` | Stable | Sub-agent based deep research |
| `deleting` | Stable | Delete files |
| `git_ops` | Stable | Read-only git inspection (status/diff/log/branch/show/files) |
| `hive` | Stable | Sub-agent spawning, consolidation, blackboard |
| `knowledge` | Stable | Keyword knowledge base (list/store/query) |
| `memory` | Stable | Persistent memory management |
| `modifying` | Stable | Edit text in existing files |
| `planning` | Stable | todo.md plan create/add/complete/update (316 lines) |
| `reading` | Stable | Read files |
| `reasoning` | Stable | LLM chain-of-thought reasoning (v3.0.0, HyperReasoningEngine) |
| `shortcuts` | Stable | Command shortcuts |
| `system` | Stable | System inspection (disk, process, env, audit, info) |
| `task` | Stable | Checklist task management on todo.md (v2.1.0) |
| `terminal` | Stable | Sandboxed command execution (SovereignSandbox) |
| `test_runner` | Stable | Test runner (streaming) |
| `web_search` | Stable | Bing RSS + DuckDuckGo web search / URL fetch |
| `bash_timeout_control` | Unimplemented stub | Bash timeout control |
| `browser_open` | Unimplemented stub | Open local HTML in a browser |
| `fault_tolerant_command_runner` | Unimplemented stub | Retry/fault-tolerant command runner |
| `file_path_resolver` | Unimplemented stub | Resolve ambiguous file paths |
| `live_news_tool` | Unimplemented stub | Current-date-aware news search |
| `long_running_command_handler` | Unimplemented stub | Async/background command support |
| `news_aggregator_live` | Unimplemented stub | Aggregate multiple news sources |
| `nexus_codebase_research` | Unimplemented stub | Recursive dependency/research mapping |
| `safe_file_path_tracking` | Unimplemented stub | Track files outside the project dir |
| `sandbox_path_validation` | Unimplemented stub | Validate workspace-only sandbox paths |
| `sandbox_path_validator` | Unimplemented stub | Enforce workspace boundaries |
| `workspace_path_guard` | Unimplemented stub | Guard paths outside the workspace |
| `workspace_path_validation` | Unimplemented stub | Validate paths stay in the workspace |

## Security
- `threat_patterns.py` — Threat scanner: 41 regex patterns across 3 scopes (`all` / `context` / `strict`)
- `terminal` and `test_runner` execute through `SovereignSandbox` (3-tier sandbox + risk scoring)
- `bash` is retired/disabled (`DISABLED_TOOL_NAMES = {"bash"}` in `tools/nexus_tools/registry.py`, no `tools/bash/` dir) — `terminal` is the only command tool
