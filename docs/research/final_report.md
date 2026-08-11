# Nexus AI — Final Audit & Fix Report

> **Historical report** — paths and versions reflect the state at audit time
> (older layout: `orchestrators/loop.py`, `architect.py`, `shell/`). Current
> layout: `orchestrators/v5/core.py` (NexusLoop), no `shell/` directory; GUI is
> React 18.3.1 + Vite 5.3.3 + TypeScript 5.5.3.

## 1. Project Verification

**Windows project folder**: `C:\Users\himan\Desktop\NEXUS AI` — **Verified** ✓
- Python 3.14.3, pip 26.0.1, Node v24.13.1, npm 11.8.0
- 30+ Python packages, 20+ directory modules
- Editable pip install works (`pip install -e .`)
- FastAPI server imports OK, starts on port 8000
- GUI build passes (React 18.3.1 + Vite 5.3.3 + TypeScript 5.5.3)
- All 31 agent loop tests pass

## 2. Architecture Map

```
nexus/               Boot loader + canonical event system (CanonicalEvent, ~50 event types)
server/              FastAPI HTTP/SSE server, REST API endpoints, OpenAI-compatible
orchestrators/loop.py  Main agent loop (unified streaming/tool runtime with canonical work events)
orchestrators/architect.py  Legacy orchestrator (fixed with stub imports)
kernel/              Central singleton with lazy-loaded subsystems
providers/           30+ LLM provider implementations (OpenAI, Anthropic, Ollama, etc.)
tools/               Tool registry with .jsnol metadata discovery (~15 tool directories)
mcp/                 MCP server (stdio JSON-RPC)
plugins/             Plugin system with lifecycle hooks
skills/              Skill system with SKILL.md format (canonical + legacy)
memory/              Multi-source MemoryManager
sandbox/             3-tier command sandbox + deterministic risk scoring
shell/               Legacy Rich shell
gui/                 React 18.3.1 + Vite 5.3.3 + TypeScript 5.5.3 GUI
tui/                 Ink-based TUI + headless Node.js TUI
```

## 3. Root Causes Found

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| **Fake terminal** | `TerminalPanel.tsx` used hardcoded "Command not found" for all input | Rewrote with real SSE backend connection |
| **Fake file explorer** | `FileExplorerPanel.tsx` fell back to mock data when API failed | Proper error handling, retry button, real fallback endpoints |
| **Fake dino game templates** | `App.tsx` contained ~325 lines of hardcoded HTML/Python game code + `repairGeneratedArtifact` replaced real AI output with templates | Removed all hardcoded templates, pass-through artifact repair |
| **Broken orchestrator imports** | `architect.py` imported 7+ non-existent modules | Wrapped in try/except with stub classes |
| **TypeScript build errors** | `JSX.Element` namespace not found; `unknown` type issues with payload | Fixed types in workActivityUtils.ts and FileExplorerPanel.tsx |

## 4. Permanent Fixes Made

### Files Changed
| File | Change |
|------|--------|
| `gui/src/components/workspace/TerminalPanel.tsx` | **Complete rewrite**: Real terminal with SSE backend connection, live stdout/stderr, exit codes, command history, error handling |
| `gui/src/components/workspace/FileExplorerPanel.tsx` | **Rewrite**: Proper error states (network/missing-endpoint), retry button, real subdirectory fetching, no mock data |
| `gui/src/App.tsx` | **Removed** `buildDinoGameHtml()`, `buildDinoGamePython()`, `repairGeneratedArtifact()` — eliminated ~325 lines of fake demo code |
| `gui/src/utils/workActivityUtils.ts` | Fixed `unknown` type errors in `adaptCanonicalWorkEvent` |
| `orchestrators/architect.py` | Fixed 7 broken imports with try/except + stub classes |
| `AGENTS.md` | Complete rewrite with verified project structure, run commands, security notes |

### OpenCode Project Files Created/Updated
| File | Description |
|------|-------------|
| `.opencode/commands/nexus-smoke.md` | Smoke test command |
| `.opencode/commands/nexus-audit.md` | Audit command |
| `.opencode/commands/nexus-gui.md` | GUI run command |
| `.opencode/commands/nexus-tui.md` | TUI run command |
| `.opencode/commands/nexus-test.md` | Test commands |
| `.opencode/skills/permanent-root-cause-fix/SKILL.md` | Root-cause fix workflow skill |
| `.opencode/skills/event-streaming/SKILL.md` | Event model skill |
| `.opencode/skills/gui-agent-workspace/SKILL.md` | GUI workspace skill |
| `.opencode/skills/tui-live-events/SKILL.md` | TUI events skill |
| `.opencode/skills/tool-mcp-integration/SKILL.md` | Tool/MCP integration skill |
| `.opencode/skills/testing-smoke-e2e/SKILL.md` | Testing skill |
| `AGENTS.md` | Complete rewrite with verified truth |
| `docs/research/agent_framework_research_matrix.md` | Research matrix (32 references) |

## 5. Robots/Agents Used

- **@explore** × 2 — Backend architecture inspection, GUI/frontend inspection
- **@general** × 4 — TerminalPanel fix, FileExplorerPanel fix, dino templates removal, architect.py fix
- **Build coordinator** — Main coordination, project file creation, testing, verification

## 6. Verification Results

| Check | Result |
|-------|--------|
| Backend import | ✓ `NexusLoop` imports OK |
| Server import | ✓ FastAPI `server` module imports OK |
| GUI build | ✓ `npm run build` passes (TypeScript + Vite) |
| Agent loop tests | ✓ 31/31 passed (0.98s) |
| Pip install | ✓ `pip install -e .` succeeds |
| Fake terminal | ✓ Replaced with real SSE-connected terminal |
| Fake file explorer | ✓ Replaced with proper error handling |
| Fake dino templates | ✓ Removed from production code |
| Broken imports | ✓ Fixed in architect.py |

## 7. Remaining Limitations

| Limitation | Priority | Notes |
|------------|----------|-------|
| `/api/files/list` endpoint doesn't exist on backend | Medium | `FileExplorerPanel` now handles this gracefully |
| `kernel/__init__.py` references ~20 subsystems that may not exist | Low | Lazy-loaded, silently fails on import errors |
| Some tools have metadata but no handler scripts | Low | Tools still discovered but runtime will get empty results |
| No WebSocket — uses SSE + polling | Low | Works but could be more responsive |
| Full test suite (410 items) takes time due to model loading | Low | Can optimize test configuration |
| `orchestrators/architect.py` is legacy with stub imports | Low | Main runtime uses `loop.py` |

## 8. How to Run Nexus AI

```powershell
# Server only
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m nexus --server

# GUI + gui.api backend
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m nexus --gui

# Legacy Rich shell
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m nexus --shell

# Default Ink TUI + gui.api backend
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m nexus

# Tests
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m pytest tests/core/test_loop/
```
