# ask_question

Creates a user-facing multiple-choice question for interactive Nexus
surfaces. The tool returns a `[QUESTION:{...}]` marker understood by the TUI
question panel and includes the same payload in `ToolResult.metadata.question`
for other clients.

Parameters:

- `prompt` — required question text.
- `options` — one or more answer choices; at most eight are retained.
- `allow_custom` — whether the user may type an answer outside the choices.

This is a conversation-state action, so it is not marked read-only and is not
automatically retried.
