# GUI (React Frontend)

React 18 + Vite + TypeScript frontend with Tailwind CSS.

**Version:** 2.0.0

## Structure
- `src/App.tsx` — Root component orchestrating sidebar, chat, editor, terminal, settings
- `src/components/MainChat.tsx` — Core chat component (~1600 lines) with SSE streaming
- `src/components/SettingsPanel.tsx` — Settings modal (515 lines)
- `src/components/FileExplorer.tsx` — Workspace file browser (413 lines)
- `src/components/ActivityTimeline.tsx` — Thinking/event visualization
- `src/components/TerminalPanel.tsx` — Terminal drawer
- `src/components/ChatHistory.tsx` — Session sidebar
- `src/components/ApprovalPanel.tsx` — Co-Pilot approval UI
- `src/components/MonacoEditor.tsx` — File editor wrapper
- `src/hooks/useStreamChat.ts` — SSE chat streaming hook (413 lines)
- `src/lib/api.ts` — API client (60+ endpoints)
- `src/lib/store.ts` — Zustand state management
- `api.py` — FastAPI backend (2800+ lines) co-located for GUI functionality

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
