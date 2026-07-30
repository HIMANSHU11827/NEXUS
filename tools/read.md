# Tools

NEXUS AI tool system — 19 registered tools with `.jsnol` metadata discovery, BaseTool abstract class, and ToolRegistry.

**Version:** 2.0.0

## Structure
```
tools/
  <toolname>/
    <toolname>.jsnol    — JSON tool definition (schema + metadata + version)
    <toolname>.md       — Documentation
    read.md             — Directory docs
    scripts/<tool>.py   — Handler extending BaseTool with __version__
```

## Registered Tools
| Tool | Handler | Status |
|------|---------|--------|
| `bash` | BashTool | Stable |
| `code_search` | CodeSearchTool | Stable |
| `creating` | CreatingTool | Stable |
| `deep_research` | DeepResearchTool (sub-agent based) | Stable |
| `deleting` | DeletingTool | Stable |
| `git_ops` | GitOpsTool | Stable |
| `hive` | HiveTool (sub-agent spawning) | Stable |
| `knowledge` | KnowledgeTool | Stable |
| `memory` | MemoryTool | Stable |
| `modifying` | ModifyingTool | Stable |
| `planning` | PlanningTool (270 lines) | Stable |
| `reading` | ReadingTool | Stable |
| `reasoning` | ReasoningTool (v2 — decomposition, uncertainty, verification) | Stable |
| `shortcuts` | ShortcutsTool | Stable |
| `system` | SystemTool (v2 — disk, process, env, audit, info) | Stable |
| `task` | TaskTool | Stable |
| `terminal` | TerminalTool | Stable |
| `test_runner` | TestRunnerTool (streaming) | Stable |
| `web_search` | WebSearchTool (DDG/Bing) | Stable |

## Security
- `threat_patterns.py` — Content-level threat scanner (55 regex patterns across 3 scopes)
- 3-tier sandbox integration via SovereignSandbox
- Risk scoring via CommandRiskScorer
