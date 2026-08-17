# Nexus TUI v3.0 Redesign

## Design Direction: Activity-Rich Developer Design

Based on deep analysis of OpenCode TUI (Go + Bubble Tea), Claude Code, Codex CLI,
and React Ink patterns. Selected over:

1. **Minimal Chat-First** — Rejected: hides Nexus's differentiation (tool/agent visibility)
2. **Split-View Workspace** — Partially incorporated: sidebar for hive/tasks

### Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | React Ink 5.x (stay) | Already integrated, full JS ecosystem |
| State | React + useReducer | Better than 30+ useState hooks |
| Rendering | Cached + incremental | Like OpenCode's cacheItem pattern |
| Scrolling | Virtual viewport | Only render visible messages |
| Streaming | SSE + diff patching | Push-based, not polling |
| Input | Enhanced TextInput + panel | `\` for newline, `@` for file autocomplete |
| Activity cards | Collapsible Ink components | Replace ASCII boxes |
| Hive display | Nested expandable rows | OpenCode's nested tool call pattern |
| Status bar | Fixed bottom bar | Model, tokens, cost, sandbox, voice |
| Navigation | Keyboard shortcuts | Ctrl+K commands, Ctrl+N new, Esc cancel |

### Files Changed
- tui/nexus-tui.tsx — main app refactor
- tui/renderer.tsx — chat renderer (new)
- tui/activity-card.tsx — tool/activity cards (new)
- tui/hive-panel.tsx — Hive agent display (new)
- tui/status-bar.tsx — status bar (new)
- tui/input-composer.tsx — enhanced input (new)
- tui/theme.ts — theme system (new)
- tui/types.ts — shared types (new)
