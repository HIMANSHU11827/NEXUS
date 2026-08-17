# NEXUS TUI design QA — 2026-08-11

## Reference and rendered state

- Welcome-logo reference: `C:\Users\himan\AppData\Local\Temp\codex-clipboard-f4938805-fe71-4327-a17f-24974b4ad592.png` (Gemini CLI gradient terminal wordmark supplied by the user).
- Welcome implementation: `tui/artifacts/tui-welcome-implementation.png`, rendered from the real Ink welcome component at 110 × 30 cells.
- Welcome comparison: `tui/artifacts/tui-welcome-comparison.png`.
- Question-state implementation: `tui/artifacts/tui-question-implementation.png`, rendered from the real 52-column Ink inspector component.
- Reference: `C:\Users\himan\AppData\Local\Temp\codex-clipboard-70094673-c956-402c-b4cd-59121584fc5c.png` (latest supplied collapsed activity-row state).
- Implementation: `tui/artifacts/tui-redesign-implementation.png`, rendered from the real Ink components at 160 × 44 cells with Cascadia Mono.
- Side-by-side comparison: `tui/artifacts/design-qa-comparison.png`.
- Additional real-state reference: `C:\Users\himan\AppData\Local\Temp\codex-clipboard-a9741d6a-07da-4672-b908-e979272e24aa.png` (repeated failed searches and long URL rows).
- State: an active verification run with plan, search, file, Skill, MCP, Hive, and terminal activity; 29% context; changed files; busy composer.

## Required surfaces checked

- A new, idle session shows a centered terminal-native NEXUS block wordmark with a blue-to-purple-to-pink gradient, concise product description, and quick-start line.
- The large wordmark is responsive: compact terminals receive a single-line gradient NEXUS mark and never overflow; once chat or activity starts, the transcript reclaims the entire viewport and the compact header remains.
- Questions use a dedicated "NEXUS NEEDS YOUR INPUT" surface, a readable prompt, full-width selectable answer rows, an explicit custom-answer row, and visible keyboard instructions.
- Arrow/wheel navigation includes the custom-answer row; Enter and number shortcuts resolve exactly one answer, while custom submission closes question mode and clears its draft state.
- Because terminal `Ctrl+I` and Tab share the same ASCII byte, an idle Tab/Ctrl+I event now cycles the inspector whenever no trace row can consume it; `Ctrl+O` is the reliable inspector shortcut in every state and is shown in the header/composer.
- Conversation remains the primary surface, with a compact run header and a focused two-row composer.
- Submitted user messages use a full-width filled dark row with the `›` prompt, matching the supplied Codex reference.
- Nexus replies use their own full-width filled dark row, visually pairing the two sides of the conversation without changing live tool rows.
- Live rows distinguish plan, tool, terminal, file, test, search/web, Hive, approval, and error states without exposing reasoning text.
- Every emitted tool/activity remains its own row; retries and repeated failures are never grouped or hidden.
- Search URLs render as readable hostnames, and Skill/MCP names are normalized into human-readable action labels.
- Every activity row has a default disclosure chevron. Click or focus with Tab and press Enter to expand/collapse details, including plans.
- Collapsed tool, web-search, file, Skill, MCP, Hive, plan, test, and terminal rows always use the same full-width `#292929` filled surface as user and NEXUS messages; selection or expansion is not required.
- Collapsed activity uses exactly one compact line: `› tool · target/query · duration`. It does not repeat kind/status/verb labels such as `[DONE]` or `Failed`.
- Failed, blocked, cancelled, or denied activity communicates status by turning the complete collapsed row red; no redundant failure word is added.
- Expanded activity details use the same full-width filled `#292929` transcript surface as user and Nexus messages, with inset content and no drawn border.
- Completed lifecycle updates preserve the last meaningful query, filename, command, URL, or target, so compact rows consistently follow `› tool · target · duration`.
- File activity uses the basename in the compact row while retaining the full path inside expanded details.
- `assistant.progress` narration is excluded from the interactive tool trace; canonical tool lifecycle events remain individually visible.
- Active activities derive elapsed time from `startedAt` until the backend supplies a final duration.
- Repeated tool/agent names are removed from the middle target (for example, `testing agent · checking edge cases · 12s`).
- Inspector prioritizes task, current activity, context, and changed files.
- CHANGES displays only each basename while retaining the complete path in the underlying file record.
- One terminal-safe shared spinner is used only while work is active; completed rows are static.
- Tab / Shift+Tab focus trace rows and Enter expands the selected row. Ctrl+I changes inspector mode.
- Compact widths 20, 39, 57, 58, and 78 columns are rendered in tests and checked for line overflow.

## Comparison history

1. The initial rail and composer left too much blank space, hid meaningful live work, and used hard-coded layout rows. Central layout budgeting and the selected chat-first inspector were implemented.
2. Review found inaccessible activity details, narrow-composer overflow risk, and fixture-only trace proof. Keyboard focus/expansion, compact Ink rendering, and SSE-to-render coverage were added.
3. The submitted Codex reference added the filled user-message treatment. History rows now render it directly and the rendered artifact was regenerated.
4. The prior linked-node and mixed glyph animations were replaced by one shared, terminal-safe active spinner. The status header now documents Ctrl+I for the inspector.
5. Nexus reply content was placed in the exact same full-width filled transcript row as the user message, keeping the `Nexus >` role label inside the box; the implementation artifact was regenerated and inspected.
6. Real news-search output revealed duplicated labels, raw URLs, and inconsistent Skill/MCP naming. Every event remains visible, successful URLs show their hostname, and Tool/Skill/MCP/Hive rows share the same kind/status/action hierarchy. Every row now exposes a disclosure chevron with mouse and keyboard expansion, including plans.
7. The trace was tightened to a single-line disclosure format (`› tool · target · duration`). Bracketed DONE/LIVE/FAIL badges and repeated verbs were removed; a failed row is entirely red and expands only on demand.
8. The outlined expanded-detail card was replaced with the same edge-to-edge filled surface used by user and Nexus transcript rows. Border glyphs were removed and the content retains clear internal spacing.
9. Runtime evidence showed target-less `assistant.progress` rows and terminal lifecycle events overwriting earlier queries/paths. Progress narration is now filtered, meaningful targets survive lifecycle merges, and file rows show readable basenames between tool and duration.
10. Final review found running rows lacked elapsed time and Hive summaries repeated the agent name. Live duration now derives from the activity start time, and repeated leading names are stripped from the target.
11. The CHANGES rail exposed long absolute paths. It now renders concise basenames such as `fallback.ts` and `fallback.test.ts`; Windows and POSIX path extraction are covered by tests.
12. Collapsed activity rows previously gained a filled surface only while running or focused. Every activity now uses the shared transcript surface in collapsed and expanded states, with focus and failure still communicated through text and chevron color.
13. The empty-session surface previously opened into a large blank transcript. It now introduces NEXUS with a centered native Ink block wordmark using the supplied blue-purple-pink gradient reference, while preserving the dense working layout after the first message.
14. Runtime capture exposed an unsupported leading `>` consuming invisible BigText width and the font renderer painting its default black background. The unsupported glyph was removed and the wordmark background is now explicitly transparent, restoring true horizontal centering with no dark rectangle.
15. A second runtime capture showed the third-party BigText canvas still reset padded cells to the terminal's black default and left the mark too low. The welcome component now renders the compact CFonts glyph data inside a NEXUS-colored Ink text surface, removes all alignment padding, and top-aligns the complete welcome block two rows below the header.
16. Keyboard review found Windows Terminal exposes Ctrl+I as Tab, while question review found unreachable custom selection and duplicate/stale custom submission. Idle Tab/Ctrl+I now advances the inspector, and the question flow was rebuilt around deterministic selection helpers and clear filled answer rows.

## Verification

- `tui/npm.cmd run build`: passed.
- `tui/npm.cmd test`: passed, including compact render and canonical SSE-to-render trace coverage.
- `tui/welcome-logo.test.tsx`: passed at 100×18, 40×8, and 20×4 without horizontal overflow.
- Welcome-logo regression coverage also rejects ANSI black-background sequences.
- Question-panel rendering and inspector/question interaction-state tests pass.
- The real Ink welcome frame was rendered and inspected side-by-side with the supplied gradient-logo reference.
- Provider auto-selection regression tests: 2 passed.
- The provider route resolves TUI `auto` to `config/provider.yml` (`deepseek` / `deepseek-chat`) instead of drifting to OpenRouter.

final result: passed
