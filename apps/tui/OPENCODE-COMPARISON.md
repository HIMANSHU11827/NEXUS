# NEXUS TUI and OpenCode source study

Reference checkout: `.tmp/opencode-reference` at commit `89130db` from `https://github.com/anomalyco/opencode`.

## What OpenCode does

OpenCode is a TypeScript/Bun application with a package-level TUI (`packages/tui/src`) and a separate agent/server package (`packages/opencode/src`). The TUI is divided into routes, contexts, components, prompt modules, utility modules, theme/config, and plugins. Its important boundaries are:

| OpenCode area | Responsibility | NEXUS equivalent |
|---|---|---|
| `packages/tui/src/runtime.tsx` and `context/*` | Runtime/session SDK state and event synchronization | `App` state/effects in `tui/nexus-tui.tsx`, plus `/api/*` polling/SSE |
| `routes/session/*` | Session screen, sidebar, footer, questions, permissions | `NexusWorkspacePanel`, chat lines, question/panel modes |
| `prompt/*` and `component/prompt/*` | Input editing, history, attachments, autocomplete | `InputComposer`, input state, attached files |
| `config/keybind.ts` and `keymap.tsx` | Central key binding definitions and help | Inline `useInput` handler and slash command list |
| `context/event.ts` and SDK sync | Typed event subscription and projections | `adaptCanonicalEvent`, `acceptWorkEvent`, activity upserts |
| `util/scroll.ts`, `util/renderer.ts`, virtualized file preview | Bounded rendering and scroll/selection behavior | Derived `chatLines`, `chatScroll`, mouse wheel handling |
| `theme/*`, `context/theme.tsx` | Theme source of truth and theme selection | `theme.ts` exists, but main app still uses hard-coded `THEME` |
| `test/*` and component stories | Runtime/component behavior coverage | TypeScript smoke tests plus Python API/e2e checks |

## NEXUS execution and data flow

1. `nexus/__main__.py` selects the TUI/server mode; the current startup path launches the API and then `tsx tui/nexus-tui.tsx`.
2. The Ink `App` initializes session, provider/model, panel, transcript, activity, plan, voice, and terminal-size state.
3. A submitted prompt posts to `/api/chat` with `stream: true` and `canonical_events: true`.
4. The response is parsed as SSE. `message` frames append assistant text; `work_event`/`nexus.event` frames are normalized and projected into activities, plans, timelines, and working state.
5. Rendering derives bounded chat lines from history and activities, then shows the workspace plus optional sidebar/panel.
6. Abort, signal, resize, mouse, voice, and timer effects restore terminal/backend state on shutdown.

## Findings from the comparison

- OpenCode makes keymaps, prompt behavior, and event synchronization separate modules; NEXUS currently concentrates these in one very large component.
- OpenCode treats the prompt as a stateful subsystem with focused tests; NEXUS has useful parsers but no runtime input harness.
- OpenCode has an explicit theme/context path; NEXUS has reusable theme helpers but the main app still hard-codes many colors.
- NEXUS has stronger domain-specific visibility for canonical work events, Hive agents, plans, voice, and sandbox/permission state. Those should remain NEXUS-specific.
- The safest migration path is incremental: extract pure adapters/reducers first, then move keymap/prompt/session concerns behind those boundaries. A wholesale OpenCode UI copy would discard NEXUS’s API and event contracts.

## Tool-call lifecycle: OpenCode pattern applied to NEXUS

OpenCode keeps one typed tool part keyed by a stable `callID`, then applies lifecycle transitions to that part: input/call, progress, success, failure, or cancellation. NEXUS already emits the equivalent canonical envelope through SSE:

```text
tool.started / command.started  -> running activity
command.stdout / tool-chunk      -> append output to that activity
tool.completed / command.finished -> done activity
tool.failed / error              -> error activity
run.cancelled                    -> cancelled activity
guardrail.blocked / denied       -> blocked activity
```

The previous TUI incorrectly deduplicated every event using only `event_id`/`id`. Since lifecycle updates can intentionally reuse the logical tool-call ID, output and completion events could be discarded. The TUI now separates:

- activity identity: stable `call_id`/`tool_call_id`/event ID, used to update one row;
- delivery identity: event ID plus sequence/lifecycle/chunk data, used only to reject true replay duplicates.

Streamed `chunk`/`stdout`/`stderr` data is accumulated with bounded existing previews, and inline rows now label failed, cancelled, and blocked calls explicitly. This adopts OpenCode’s state-transition idea without replacing NEXUS’s canonical event protocol.

## Improvements applied in this pass

- Escape now aborts an active chat turn.
- Ctrl+K opens the slash command palette.
- Input hints no longer promise unsupported multiline editing.
- Short terminals are allowed to use their actual height instead of being forced to 25 rows.
- Activity output strips control characters and respects narrow panel widths.
- Hive row expansion follows newly selected agents.
- Activity/Hive panel widths are derived from the available workspace width.
- The live Hive panel now reads `/api/hives`; configured idle personas from `/api/agents` no longer appear as active sub-agents.

## Next recommended work

1. Make `tui/types.ts` the single event/UI type contract.
2. Extract a tested SSE parser and canonical-event reducer from `App`.
3. Add a central keymap and an Ink input harness for cancellation, questions, palette, scrolling, and resize.
4. Add a capability-aware theme (`NO_COLOR`, `TERM=dumb`) and remove hard-coded main-app colors.
5. Add startup readiness retry and one idempotent asynchronous shutdown supervisor.
