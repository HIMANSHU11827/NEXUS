# NEXUS TUI interaction research

This redesign treats the terminal as a focused coding workspace: transcript first,
durable tool lifecycle rows second, and configuration or agent detail on demand.

## Patterns adopted

- Plain, continuously visible model and permission state. Permission mode is a
  safety control, not an icon or hidden setting.
- A compact composer with the currently relevant escape hatch while a run is
  active. One session has one live turn; a second prompt is kept as a draft.
- Explicit run status only. The UI never manufactures a model thought or plan
  from prompt keywords.
- Small terminal header and text-first status labels. Decorative banners and
  ambiguous emoji cost vertical space and are unreliable across Windows shells.
- Tool, task, and agent information stays inspectable, but does not displace the
  active conversation.

## Reference material

- Codex workflows emphasize inspectable, reviewable work and verification:
  https://developers.openai.com/codex/use-cases
- Claude Code documents interactive sessions, resuming work, explicit model
  choice, and permission modes including plan mode:
  https://docs.anthropic.com/en/docs/claude-code/cli-usage
- OpenCode documents fuzzy `@` file references, slash commands, a detail toggle,
  compacting, session control, and attention for questions/errors/completion:
  https://opencode.ai/docs/tui/
- OpenCode permission rules make allow/ask/deny a first-class product control:
  https://dev.opencode.ai/docs/permissions/

## Next implementation tranche

1. Extract session/run state, panel data, key bindings, and composer control out
   of `nexus-tui.tsx`.
2. Add a focusable inspector that is full-screen on narrow terminals rather than
   hiding plans, agents, and approvals.
3. Replace static slash completion with a searchable command palette and add
   real `@` file suggestions plus input history.
4. Add Ink interaction tests for cancellation, narrow terminals, panel focus,
   offline/reconnect state, and streaming scroll anchoring.
