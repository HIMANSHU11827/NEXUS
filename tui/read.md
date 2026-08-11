# TUI (Ink)

Nexus TUI v3.0 — activity-rich Ink terminal UI over the FastAPI server on :8000. See `nexus-design.md` and `FINAL-REPORT.md` for the redesign details.

**Version:** 3.0.0

## Usage
```
powershell
cd tui
npm install
npm start
```

**Note:** This is NOT the live terminal — it is an Ink UI over the API. Use `python -m nexus` to launch the in-process terminal (TUI + backend together).

## Components
- `nexus-tui.tsx` (2517 lines) — main entry / app shell
- `helpers.ts` — shared command-registry adapter, matching, and safe palette normalization. Slash commands come from `nexus/commands.py` through `GET /api/commands`; the TUI has no separate hard-coded command catalog.
- `workspace-panel.tsx`, `chat-view.tsx`, `activity-card.tsx`, `inline-activity.tsx` — workspace sidebar, chat, activity stream
- `hive-panel.tsx`, `task-list.tsx`, `status-bar.tsx`, `details-panel.tsx` — hive agents, tasks, status, details
- `command-palette.tsx`, `input-composer.tsx`, `banner.tsx` — command palette, input, banner
- `nexus-shell.tsx` — legacy shim wrapper (status + hive + activity)
- `nexus-tui-headless.ts` — headless entry
- `theme.ts` — theme system
- `live-agent-state.ts`, `tool-call-state.ts` — live agent / tool-call state
- `terminal-markdown.ts` — terminal-safe markdown rendering
- `setup_wizard.py` — Python setup wizard for TUI/backend configuration
