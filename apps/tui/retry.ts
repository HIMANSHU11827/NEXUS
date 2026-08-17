/**
 * Pure, side-effect-free retry-resolution logic for the TUI `/retry` command.
 *
 * The interactive `/retry` handler reuses the ORIGINAL user prompt (never a
 * rebuilt/truncated one, and never a slash command) and re-submits it through
 * the real chat backend (`handleSubmit` -> POST /api/chat). This module
 * isolates the *decision* so it can be unit-tested without launching the Ink
 * TUI. The presence of a non-null return is exactly what lets the handler
 * proceed to a real backend call — proving `/retry` is not a no-op.
 */

export interface ChatMessage {
  role: string;
  content?: unknown;
}

/**
 * Returns the most recent user prompt worth retrying, or `null` when there is
 * nothing to retry:
 *   - empty / missing history
 *   - the last user message is a slash command (e.g. another `/retry`)
 *   - every user message is blank/whitespace
 */
export const resolveRetryPrompt = (history: ChatMessage[]): string | null => {
  const lastUser = [...(history || [])]
    .reverse()
    .find((m) => m.role === 'user' && String(m.content || '').trim());
  const prompt = String(lastUser?.content || '').trim();
  if (!prompt || prompt.startsWith('/')) return null;
  return prompt;
};
