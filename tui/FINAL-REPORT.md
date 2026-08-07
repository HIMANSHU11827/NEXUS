# Nexus TUI v3.0 — Multi-Agent Redesign Report

## Overview
Complete redesign of the Nexus TUI using patterns from OpenCode TUI (Go + Bubble Tea),
adapted for React Ink + TypeScript. Focuses on activity visibility, performance,
accessibility, and real-time Hive agent monitoring.

## Research Phase

### OpenCode TUI Source Analysis (v1.18.11)
- **Repo**: github.com/opencode-ai/opencode (archived, now "Crush")
- **Files analyzed**: tui.go, chat.go, message.go, list.go, editor.go, sidebar.go,
  status.go, theme.go, styles.go, split.go, container.go, overlay.go, util.go

### Key Patterns Adopted

| Pattern | Source | Nexus Adaptation |
|---------|--------|-----------------|
| Render caching | list.go | useMemo + key-based |
| Viewport scrolling | list.go | Flexbox + height caps |
| Message rendering | message.go | Separated renderer |
| Tool call rows | message.go | ActivityCard expand/collapse |
| Status bar | status.go | StatusBar component |
| SplitPane layout | split.go | Box flexDirection |
| Theme system (50+) | theme.go | theme.ts dark/light |
| Agent tool nesting | message.go | HivePanelBody |
| PubSub streaming | list.go | SSE + incremental |
| Spinner + status | list.go | StreamingIndicator |

### Sources
1. GitHub opencode-ai/opencode (source code)
2. Charmbracelet Bubble Tea docs
3. Lipgloss styling guide
4. React Ink 5.x docs
5. WCAG 2.1 contrast guidelines
6. ANSI/xterm escape sequence reference


## Design Decision
**Selected: Activity-Rich Developer Design**
Rejected: Minimal Chat-First (hides differentiation), Split-View (narrow terminals)

## Files Created (8 new, 2 modified)

| File | Lines | Purpose |
|------|-------|---------|
| types.ts | 203 | Shared types |
| theme.ts | 171 | Theme system |
| activity-card.tsx | 114 | Activity cards |
| hive-panel.tsx | 123 | Agent panel |
| status-bar.tsx | 82 | Status bar |
| input-composer.tsx | 57 | Enhanced input |
| nexus-shell.tsx | 109 | Wrapper |
| v3-smoke.test.ts | 63 | Tests |

## Test Results

### Unit Tests — ALL PASSING
- choice-question ✅ terminal-markdown ✅ startup-session ✅
- sse-parser ✅ v3-smoke ✅ (19 component tests)

### Runtime — 19/21 pass (2 pre-existing env issues)
### TypeScript — npx tsc --noEmit: ZERO ERRORS

## Remaining
- Wire components into App render incrementally
- Ctrl+K command palette, @ autocomplete
- Virtual scrolling, diff view, session restore
