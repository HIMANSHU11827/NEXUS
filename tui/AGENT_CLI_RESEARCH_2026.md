# NEXUS agent CLI/TUI research and idea backlog

Research date: 2026-08-11. This is a product backlog, not a promise that every
item exists already. The goal is a calm, trustworthy terminal workspace rather
than a decorative dashboard.

## P0 — trust, control, and recovery

1. **Three explicit execution modes** — Ask, Plan, and Act must be persistent
   mode chips with backend enforcement; Plan cannot write or execute mutations.
2. **Resource-aware approval card** — show operation class, exact path/command/
   URL, sandbox, risk and diff; offer once, session, matching-rule, or deny.
3. **Protected-operation blocklist** — critical commands and secret reads stay
   blocked even in broad auto-approval mode.
4. **Workspace trust screen** — warn before operating in a home, parent, or
   untrusted directory; display current cwd, sandbox, and network scope.
5. **Verified provider save** — Test a model/provider with a live completion,
   show latency/result, then save only on success without replacing working config.
6. **Operator diagnostics** — F8 or `/doctor` reports API, model, MCP, queue,
   config validity, and a next recovery action without exposing secrets.
7. **Deterministic repair lane** — `/repair` uses local typed actions, one-use
   approvals, audit logging, and no model-generated recovery commands.
8. **Per-turn checkpoints** — every completed run records changed files, diff,
   commands and tests; `Revert this turn` describes non-reversible effects.

## P1 — productive agent interaction

9. **Busy-input policy** — replace a simple block with Interrupt, Queue, and
   Steer; a steer message is injected at a safe tool boundary and visibly marked.
10. **Draft parking** — Ctrl+S stores multiline drafts and attachments only in
   memory; restore/discard via an overlay, never silently persist secrets.
11. **External editor composer** — Ctrl+E opens `$EDITOR` for long prompts;
   multiline paste becomes a collapsed size preview rather than scrollback noise.
12. **Context chips** — `@` fuzzy picker for files, directories, skills, agents,
   MCP resources; chips have token cost, pin/remove, and secret/binary exclusion.
13. **Progressive tool details** — compact lifecycle row by default; Ctrl+D or
   per-row expand shows input, command, stdout/stderr summary, duration and diff.
14. **Real session picker** — searchable resume screen with title, cwd, model,
   age, run status, dirty file count, last prompt, and compact recap.
15. **Command palette** — searchable Ctrl+P palette for actions, arguments,
   descriptions and keybindings, plus recent commands and project commands.
16. **Reusable command library** — user/project scoped `/test`, `/review`,
   `/ship` templates with source, model, agent, and policy preview.

## P2 — long-running and multi-agent work

17. **Isolated worktree chooser** — Current workspace, named Git worktree, or
   sandbox before broad/risky tasks; each subagent exposes branch and path.
18. **Agent launch contract** — a launch card declares model, task, budget,
   permissions, working directory and completion criteria before execution.
19. **Capability inspector** — active tools, skills, MCP servers, provider
   profile and exact authority are session-scoped and inspectable.
20. **Attention policy** — opt-in sounds/notifications only for approval,
   question, failure, completion and subagent completion; never routine spam.
21. **Background-run controls** — pause/resume/cancel plus elapsed time, latest
   tool, output summary and a reliable reconnect indicator.
22. **Headless parity** — `nexus run --output json|stream-json` with stable event
   schema, nonzero error codes, explicit max turns and noninteractive policies.

## P3 — durable operation and accessibility

23. **Transparent memory panel** — inspect project decisions/daily notes,
   injection budget/index health and use a clear forget/remove operation.
24. **Safe plugin trust center** — install does not enable; show origin, version,
   permissions, tools, changelog, inspect/diff and enable separately.
25. **Responsive status tiers** — dense footer changes at narrow/medium/wide
   widths while keeping model, context, approval mode, cwd, run time and agent
   count visible in text.
26. **Accessibility and terminal capability modes** — no-color/mono/high-contrast
   themes, semantic status labels, screen-reader-friendly output and terminal title.

## Recommended implementation order

1. Modes + approval cards + workspace trust.
2. Provider verification + diagnostics + connection/recovery UX.
3. Context chips, details toggle, sessions and checkpoints.
4. Worktree agents, busy-input steering, drafts and notifications.
5. Memory, plugins, accessibility, headless parity.

## Primary sources

- Hermes CLI and security: https://hermes-agent.nousresearch.com/docs/user-guide/cli
  and https://hermes-agent.nousresearch.com/docs/user-guide/security/
- OpenClaw CLI, TUI and memory: https://docs.openclaw.ai/cli/openclaw ,
  https://docs.openclaw.ai/web/tui , https://docs.openclaw.ai/concepts/memory
- OpenCode TUI, commands and permissions: https://opencode.ai/docs/tui/ ,
  https://opencode.ai/docs/commands/ , https://opencode.ai/docs/permissions/
- Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code/cli-usage
- GitHub Copilot CLI: https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli
- Gemini CLI: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/cli-reference.md
- Aider modes: https://aider.chat/docs/usage/modes.html
- Continue CLI: https://docs.continue.dev/cli/quickstart
- OpenHands CLI: https://docs.openhands.dev/openhands/usage/cli/quick-start
