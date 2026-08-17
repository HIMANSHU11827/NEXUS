"""V5 Context Builder - deterministic multi-turn conversation memory.

Derives genuine conversation history for the V5 loop purely from the turns
already recorded in ``runtime.turn_history``, giving the loop multi-turn
memory with V1 conversation-memory parity.

This mixin is intentionally dependency-free: it makes no LLM calls and
imports nothing from ``core`` (avoiding circular imports), so it can
be mixed into ``NexusLoopV5`` safely. Prior turns only carry ``user_input``
(the pipeline stores responses locally, not on the turn), so history is
built from user inputs only; the in-flight turn is always excluded because
its response is still streaming.
"""

from __future__ import annotations

from typing import Any, List


class V5ContextBuilder:
    """Mixin giving the V5 loop multi-turn conversation context.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.runtime`` - object with ``.turn_history`` (list of turn objects
      carrying ``turn_id``/``user_input``) and ``.current_turn``; may be None
      in exotic cases, everything is guarded.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self._current_turn_id`` - id of the in-flight turn.
    """

    def _recent_turns(self, limit: int = 6) -> List[Any]:
        """Return up to ``limit`` prior turns, oldest first, live turn excluded.

        The in-flight turn (``turn_id == self._current_turn_id``) is skipped
        because its response is still streaming. Chronological order is
        preserved (oldest first) so the derived text reads naturally.
        Fully guarded: never raises.
        """
        try:
            runtime = getattr(self, "runtime", None)
            if runtime is None:
                return []
            history = getattr(runtime, "turn_history", None)
            if not history:
                return []
            if limit <= 0:
                return []
            live_id = getattr(self, "_current_turn_id", "") or ""
            prior = [t for t in history if getattr(t, "turn_id", None) != live_id]
            return prior[-limit:]
        except Exception:
            return []

    def _conversation_history_text(self, turns: List[Any], max_chars: int = 3000) -> str:
        """Format prior turns as ``User: <input>`` lines with a header block.

        Each input is truncated to 200 characters. The block is prefixed
        with ``[CONVERSATION HISTORY]`` when non-empty and hard-sliced to
        ``max_chars`` (a mid-line cut after the slice is acceptable).
        """
        if not turns:
            return ""
        lines = []
        for turn in turns:
            text = str(getattr(turn, "user_input", "") or "")[:200]
            lines.append(f"User: {text}")
        block = "[CONVERSATION HISTORY]\n" + "\n".join(lines) + "\n"
        return block[:max_chars]

    def _apply_conversation_context(self, perceived) -> None:
        """Merge derived conversation history into ``perceived.context_summary``.

        Appends the ``[CONVERSATION HISTORY]`` block to the existing summary
        when the attribute already exists; sets it directly when missing.
        Never raises.
        """
        try:
            turns = self._recent_turns()
            count = len(turns)
            history = self._conversation_history_text(turns)
            if not history:
                return
            if perceived is None:
                self.logger.debug(
                    "[CONTEXT] perceived is None, cannot apply conversation context"
                )
                return
            try:
                current = getattr(perceived, "context_summary", None)
                if current is None:
                    setattr(perceived, "context_summary", history)
                else:
                    setattr(perceived, "context_summary", f"{current}\n\n{history}")
            except Exception:
                self.logger.debug(
                    "[CONTEXT] perceived has no settable context_summary; skipping"
                )
                return
            self.logger.debug("[CONTEXT] applied %d prior turn(s)", count)
        except Exception as e:
            self.logger.warning(
                f"[CONTEXT] failed to apply conversation context: {e}"
            )
