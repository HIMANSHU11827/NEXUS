# GUI (React Frontend)

React 18 + Vite + TypeScript frontend with Tailwind CSS.

**Version:** 2.0.0

## Structure
- `src/App.tsx` — Root component orchestrating sidebar, chat, editor, terminal, settings
- `src/components/MainChat.tsx` — Core chat component (~1650 lines) with SSE streaming
- `src/components/SettingsPanel.tsx` — Settings modal (~230 lines)
- `src/components/FileExplorer.tsx` — Workspace file browser (~420 lines)
- `src/components/ActivityTimeline.tsx` — Thinking/event visualization
- `src/components/TerminalPanel.tsx` — Terminal drawer
- `src/components/ChatHistory.tsx` — Session sidebar
- `src/components/ApprovalPanel.tsx` — Co-Pilot approval UI
- `src/components/MonacoEditor.tsx` — File editor wrapper
- `src/components/BackgroundTasksPanel.tsx` — Background task management (~510 lines)
- `src/components/HivePanel.tsx` — Sub-agent hive view
- `src/components/QueuePanel.tsx` — Task queue view
- `src/components/SafetySettings.tsx` — Safety/security settings (~540 lines)
- `src/components/WorkspaceSettings.tsx` — Workspace configuration (~350 lines)
- `src/components/ClaudeAnimation.tsx`, `CodeAnimation.tsx`, `ThinkingAnimation.tsx`, `SecondLogoAnimation.tsx` — animated logo/loading components
- `src/components/settings/` — 18 sub-panels: About, ConfigurationPanel, GatewayManager, HiveManager, McpManager, Memory, PluginManager, Providers, ScheduledJobsManager, SkillsManager, ToolsManager, Voice, KeyboardShortcuts, Appearance, Billing, Evolution, Notifications, LiveData
- `src/hooks/useStreamChat.ts` — SSE chat streaming hook (~790 lines)
- `src/lib/api.ts` — API client (60+ endpoints, ~800 lines)
- `src/lib/store.ts` — Zustand state management
- `api.py` — FastAPI backend (4700+ lines) co-located for GUI functionality

## Key Features
- Markdown rendering with tables, code blocks, headings
- SSE streaming with work event visualization
- Session management, file explorer, settings panel
- Tailwind dark/light mode via CSS custom properties
- Built output: 362 KB JS + 39 KB CSS

## Commands
```powershell
cd gui && npm run dev     # Vite dev server (port 5173)
cd gui && npm run build   # Production build
```
