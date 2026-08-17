"""V5 deterministic turn-learning mixin.

Records per-turn learning signals with zero LLM involvement, porting the V1
unified-loop learning bookkeeping to the V5 architecture: the tool-failure
gap recording in ``orchestrators/loop.py`` ``_handle_tool_failure`` (line
3126, ``self._gaps_found.append(...)``) and the mission replay JSONL audit
in ``_log_mission_replay`` (line 3255). Failures land in
``self.runtime.failures``, reflection signals in
``self.runtime.learnings``, and every turn appends one JSON line to
``<root>/.nexus_v5/replays.jsonl``.

All methods are defensive: they never raise and always log via
``self.logger`` when something goes wrong. The mixin never touches
``self.kernel`` or ``self._nate``.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import math
import os
import time
import uuid
from typing import Any, Dict

from models.providers.core.reliability import redact_secrets
from .learning_evidence import V5LearningEvidence

_DESCRIPTION_LIMIT = 200
_ERROR_LIMIT = 500
_SIGNAL_LIMIT = 300
_LEARNINGS_CAP = 200
_DIGEST_CHAR_LIMIT = 2000  # hard ceiling on the [LEARNING] block
_INPUT_LIMIT = 500
_RESPONSE_LIMIT = 200

_REPLAY_DIR_NAME = ".nexus_v5"
_REPLAY_FILE_NAME = "replays.jsonl"

_EPISODIC_RECENCY_WINDOW = 86400.0
_EPISODIC_RECENCY_ALPHA = 0.4
_EPISODIC_RELEVANCE_BETA = 0.3
_EPISODIC_IMPORTANCE_GAMMA = 0.3
_EPISODIC_SCORE_LIMIT = 200


class V5Learning(V5LearningEvidence):
    """Mixin that deterministically records turn-level learning signals.

    Inherits ``V5LearningEvidence`` (the durable, provenance-bearing
    evidence store surface) so any loop that mixes in ``V5Learning`` —
    ``NexusLoopV5`` included — automatically gains ``collect_evidence``,
    ``retrieve_lessons`` and ``_evidence_lessons_prompt`` with no core.py
    wiring change.
    """

    @staticmethod
    def _action_get(action: Any, key: str, default: Any = None) -> Any:
        """Read a field from a dict action or an object action (ActionResult)."""
        if isinstance(action, dict):
            return action.get(key, default)
        return getattr(action, key, default)

    @staticmethod
    def _reflection_get(reflection: Any, key: str, default: Any = None) -> Any:
        """Read a field from a dict reflection or an object reflection."""
        if isinstance(reflection, dict):
            return reflection.get(key, default)
        return getattr(reflection, key, default)

    @classmethod
    def _action_failed(cls, action: Any) -> bool:
        """An action failed when ``success`` is falsy or an error is present."""
        if not bool(cls._action_get(action, "success", True)):
            return True
        return bool(cls._action_get(action, "error"))

    def _runtime_storage(self, attr: str) -> Any:
        """Return the list ``self.runtime.<attr>``, creating it if missing.

        Returns None when ``self.runtime`` itself is unavailable.
        """
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            return None
        if not isinstance(getattr(runtime, attr, None), list):
            setattr(runtime, attr, [])
        return getattr(runtime, attr)

    def _record_tool_failures(self, result: Dict[str, Any]) -> int:
        """Record failed tool actions into ``runtime.failures``.

        Each failed action (dict or ActionResult object) becomes one
        ``{"type": "tool_failure", ...}`` entry. Entries are deduped by
        ``(description, error)`` and the stored list is capped at
        ``_LEARNINGS_CAP`` entries (oldest dropped) so a repeatedly
        failing tool cannot flood the bounded digest window or let
        session memory grow without bound. Returns the number of
        failures recorded.
        """
        failures = self._runtime_storage("failures")
        if failures is None:
            self.logger.debug("[LEARNING] runtime unavailable; skipping tool-failure recording")
            return 0
        actions = (result.get("actions") or []) if isinstance(result, dict) else []
        recorded = 0
        for action in actions:
            if not self._action_failed(action):
                continue
            desc = str(self._action_get(action, "description") or "")[:_DESCRIPTION_LIMIT]
            err = str(self._action_get(action, "error") or "")[:_ERROR_LIMIT]
            # Dedup: skip an identical failure already recorded this session.
            if any(
                f.get("type") == "tool_failure"
                and f.get("description") == desc
                and f.get("error") == err
                for f in failures
            ):
                continue
            failures.append({
                "type": "tool_failure",
                "description": desc,
                "error": err,
                "turn_id": self._current_turn_id or self.session_id,
            })
            recorded += 1
            # Close the durable failure-memory loop: each distinct failed
            # action is persisted so MemoryManager._prefetch_failures can
            # surface it as a PREVENTIVE VACCINE on a later turn. Without
            # this, FailureMemory.record() had zero callers and the vaccine
            # system always returned empty.
            self._persist_failure_memory(desc, err)
        if len(failures) > _LEARNINGS_CAP:
            del failures[: len(failures) - _LEARNINGS_CAP]
        return recorded

    def _persist_failure_memory(self, description: str, error: str) -> None:
        """Best-effort durable write of a distinct tool failure.
        Never raises; a persistence failure must not break the turn."""
        try:
            root_dir = getattr(self, "root_dir", None)
            if not root_dir:
                return
            from sandbox.failure_memory import FailureMemory
            fm = FailureMemory(root_dir)
            # De-dupe against what is already persisted so the vaccine
            # window is not flooded by the same repeated failure.
            existing = {r.get("error") for r in fm.recent(limit=200)}
            if error in existing:
                return
            fm.record(
                task=str(getattr(self, "_current_turn_id", "") or getattr(self, "session_id", "")),
                tool="",
                error=error,
                context={"description": description},
            )
        except Exception as e:
            self.logger.debug(f"[LEARNING] durable failure-memory write skipped: {e}")

    def _collect_reflection_signals(self, result: Dict[str, Any]) -> int:
        """Append deduplicated reflection signals to ``runtime.learnings``.

        Reads ``root_causes``, ``improvements`` and ``counterfactuals`` from
        the reflection (dict or object); entries are deduped by
        ``(type, signal)`` and the stored list is capped at
        ``_LEARNINGS_CAP`` entries (oldest dropped). Returns the count
        appended.
        """
        learnings = self._runtime_storage("learnings")
        if learnings is None:
            self.logger.debug("[LEARNING] runtime unavailable; skipping reflection signals")
            return 0
        reflection = result.get("reflection") if isinstance(result, dict) else None
        appended = 0
        for key in ("root_causes", "improvements", "counterfactuals"):
            for item in (self._reflection_get(reflection, key) or []):
                signal = str(item)[:_SIGNAL_LIMIT]
                if not signal.strip():
                    continue
                if any(
                    old.get("type") == "reflection" and old.get("signal") == signal
                    for old in learnings
                ):
                    continue
                learnings.append({
                    "type": "reflection",
                    "signal": signal,
                    "turn_id": self._current_turn_id or self.session_id,
                })
                appended += 1
        if len(learnings) > _LEARNINGS_CAP:
            del learnings[: len(learnings) - _LEARNINGS_CAP]
        return appended

    @staticmethod
    def _count_plan_steps(result: Dict[str, Any]) -> int:
        """Count plan steps from a dict/list/object plan, else 0."""
        plan = result.get("plan") if isinstance(result, dict) else None
        if plan is None:
            return 0
        if isinstance(plan, dict):
            steps = plan.get("steps")
        elif isinstance(plan, list):
            steps = plan
        else:
            steps = getattr(plan, "steps", None)
        return len(steps) if isinstance(steps, list) else 0

    def _log_turn_replay(self, perceived, result: Dict[str, Any], turn) -> None:
        """Append one JSON line to ``<root>/.nexus_v5/replays.jsonl``.

        Records the outcome of ``_log_turn_replay`` on
        ``self._replay_logged`` so the orchestrator can report the status.
        """
        self._replay_logged = False
        self._replay_entry_id = ""
        self._replay_record_sha256 = ""
        try:
            root_dir = getattr(self, "root_dir", None)
            if not root_dir:
                self.logger.debug("[LEARNING] root_dir missing; turn replay not logged")
                return
            actions = (result.get("actions") or []) if isinstance(result, dict) else []
            entry = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "turn_id": str(getattr(turn, "turn_id", "") or ""),
                "session_id": getattr(self, "session_id", ""),
                "input": redact_secrets(str(getattr(perceived, "original_input", ""))[:_INPUT_LIMIT]),
                "success": bool(result.get("success", False)),
                "n_actions": len(actions),
                "n_failed": sum(1 for action in actions if self._action_failed(action)),
                "response_preview": redact_secrets(str(result.get("response") or "")[:_RESPONSE_LIMIT]),
                "plan_steps": self._count_plan_steps(result),
            }
            entry["entry_id"] = f"replay_{uuid.uuid4().hex[:24]}"
            entry_bytes = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            entry["record_sha256"] = hashlib.sha256(entry_bytes).hexdigest()
            replay_dir = os.path.join(root_dir, _REPLAY_DIR_NAME)
            os.makedirs(replay_dir, exist_ok=True)
            with open(os.path.join(replay_dir, _REPLAY_FILE_NAME), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._replay_logged = True
            self._replay_entry_id = entry["entry_id"]
            self._replay_record_sha256 = entry["record_sha256"]
        except Exception as e:
            self.logger.debug(f"[LEARNING] turn replay log failed: {e}")

    async def _collect_turn_signals(self, perceived, result: Dict[str, Any], turn) -> None:
        """Orchestrate deterministic learning-signal collection for one turn.

        Runs tool-failure recording, reflection-signal collection and the
        JSONL turn replay, each isolated so one failure never blocks the
        others, then logs a single summary line.
        """
        failures = 0
        learnings = 0
        try:
            failures = self._record_tool_failures(result)
        except Exception as e:
            self.logger.warning(f"[LEARNING] tool-failure recording failed: {e}")
        try:
            learnings = self._collect_reflection_signals(result)
        except Exception as e:
            self.logger.warning(f"[LEARNING] reflection-signal collection failed: {e}")
        try:
            # Blocking disk write must not stall the event loop
            # (this is awaited during turn finalization).
            await asyncio.to_thread(self._log_turn_replay, perceived, result, turn)
        except Exception as e:
            self.logger.warning(f"[LEARNING] turn replay logging failed: {e}")
        evidence = 0
        try:
            # Durable evidence harvest (V5LearningEvidence mixin, if mixed in):
            # verified tool outcomes / failures / retries / verifier verdicts
            # / user corrections land in .nexus_v5/evidence.jsonl so later
            # planning turns can retrieve them. Replays are NOT re-logged
            # here -- _log_turn_replay above already owns the single replay
            # line per turn.
            collect_evidence = getattr(self, "collect_evidence", None)
            if callable(collect_evidence):
                evidence = await collect_evidence(perceived, result, turn)
        except Exception as e:
            self.logger.warning(f"[LEARNING] evidence collection failed: {e}")
        replay_status = "logged" if getattr(self, "_replay_logged", False) else "not logged"
        self.logger.info(
            f"[LEARNING] turn {self._current_turn_id or self.session_id}: "
            f"{failures} failure(s), {learnings} learning(s), "
            f"{evidence} evidence(s), replay {replay_status}"
        )

    def learning_signals_digest(self, limit: int = 6) -> str:
        """Render the collected per-turn learning signals as a bounded,
        model-readable block.

        This is the *read* half of the learning loop: ``_collect_turn_signals``
        writes ``runtime.failures`` / ``runtime.learnings`` every turn, but
        nothing injected them into the prompt, so past failures and
        reflections never influenced future behavior. Callers append the
        non-empty result to the context summary so the model can avoid
        repeating known-bad actions.
        """
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            return ""
        failures = []
        for f in (getattr(runtime, "failures", None) or []):
            if not isinstance(f, dict):
                continue
            label = str(f.get("description") or f.get("error") or "tool failure")[:120]
            failures.append("- " + label)
        learnings = []
        for l in (getattr(runtime, "learnings", None) or []):
            if not isinstance(l, dict):
                continue
            signal = str(l.get("signal") or "").strip()
            if signal:
                learnings.append("- " + signal[:160])
        parts = []
        if failures:
            parts.append("Known tool failures (avoid repeating):\n" + "\n".join(failures[-limit:]))
        if learnings:
            parts.append("Past reflections (apply if relevant):\n" + "\n".join(learnings[-limit:]))
        digest = "\n\n".join(parts)
        # Hard ceiling: even with many distinct signals the block stays
        # bounded so it cannot materially breach the context budget it
        # is appended to (see core.py injection, post memory-merge).
        if len(digest) > _DIGEST_CHAR_LIMIT:
            digest = digest[:_DIGEST_CHAR_LIMIT].rstrip() + "\n...[truncated]"
        return digest
    # ─── Episodic memory stream ──────────────────────────────────────

    @staticmethod
    def _episodic_failed(entry: Any) -> bool:
        """An entry counts as a failure when its replay data says so."""
        if not isinstance(entry, dict):
            return False
        n_failed = entry.get("n_failed", 0)
        if isinstance(n_failed, (int, float)) and n_failed > 0:
            return True
        if bool(entry.get("error")) or bool(entry.get("failure")):
            return True
        return entry.get("success") is False

    def _load_episodic(self, limit: int = 50) -> list:
        """Load replay JSONL entries as dicts, newest first, capped at ``limit``.

        Reads ``<root_dir>/.nexus_v5/replays.jsonl`` (the schema written by
        ``_log_turn_replay``); malformed lines are skipped. Never raises.
        """
        try:
            root_dir = getattr(self, "root_dir", None)
            if not root_dir:
                return []
            path = os.path.join(root_dir, _REPLAY_DIR_NAME, _REPLAY_FILE_NAME)
            if not os.path.isfile(path):
                return []
            entries: list = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        entries.append(parsed)
            entries.reverse()
            return entries[: max(0, int(limit))]
        except Exception as e:
            self.logger.debug(f"[LEARNING] episodic load failed: {e}")
            return []

    def _episodic_score(self, entry: Any, now: float | None = None) -> float:
        """Smallville-style episodic score: recency·α + relevance·β + importance·γ.

        Recency decays exponentially over 24h (``exp(-age_seconds / 86400)``),
        relevance weights replay intent (tool failures 1.0, reflections 0.8,
        planned turns 0.6, plain chat 0.3), importance is 1.0 for failure
        entries else 0.5. Normalized to 0..1; malformed entries score 0.0.
        Never raises.
        """
        if not isinstance(entry, dict):
            return 0.0
        try:
            ts = float(now) if now is not None else time.time()
            recency = 0.0
            timestamp = entry.get("timestamp")
            if isinstance(timestamp, str) and timestamp:
                try:
                    parsed = datetime.datetime.fromisoformat(timestamp)
                    age = max(0.0, ts - parsed.timestamp())
                    recency = math.exp(-age / _EPISODIC_RECENCY_WINDOW)
                except Exception:
                    recency = 0.0
            failed = self._episodic_failed(entry)
            if failed:
                relevance = 1.0
            elif entry.get("type") == "reflection" or "root_causes" in entry or "reflection" in entry:
                relevance = 0.8
            elif isinstance(entry.get("plan_steps", 0), (int, float)) and entry.get("plan_steps", 0) > 0:
                relevance = 0.6
            else:
                relevance = 0.3
            importance = 1.0 if failed else 0.5
            score = (
                recency * _EPISODIC_RECENCY_ALPHA
                + relevance * _EPISODIC_RELEVANCE_BETA
                + importance * _EPISODIC_IMPORTANCE_GAMMA
            )
            return max(0.0, min(1.0, score))
        except Exception as e:
            self.logger.debug(f"[LEARNING] episodic score failed: {e}")
            return 0.0

    def _prefetch_episodic(self, limit: int = 5) -> list:
        """Return the top ``limit`` replay entries by episodic score as digests.

        Each digest is ``{"score", "input", "outcome", "ts"}`` where outcome is
        "failure" for failed entries else "success", sorted by score desc.
        Never raises; [] on any failure.
        """
        try:
            entries = self._load_episodic(limit=_EPISODIC_SCORE_LIMIT)
            if not entries:
                return []
            ranked = sorted(
                entries,
                key=lambda entry: self._episodic_score(entry),
                reverse=True,
            )
            digests = []
            for entry in ranked[: max(0, int(limit))]:
                digests.append({
                    "score": round(self._episodic_score(entry), 4),
                    "input": str(entry.get("input") or "")[:_INPUT_LIMIT],
                    "outcome": "failure" if self._episodic_failed(entry) else "success",
                    "ts": str(entry.get("timestamp") or ""),
                })
            return digests
        except Exception as e:
            self.logger.debug(f"[LEARNING] episodic prefetch failed: {e}")
            return []
