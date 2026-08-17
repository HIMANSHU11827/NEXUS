"""Durable, provenance-bearing learning-evidence store for the V5 loop.

Closes the *read* half of the evidence loop: ``_collect_turn_signals``
already records per-turn failures/reflections, but nothing persisted
*verified* outcomes with provenance, and nothing retrieved them before a
later planning turn. This module provides:

- ``LearningEvidenceStore`` — a JSONL store at
  ``<root>/.nexus_v5/evidence.jsonl``. Every record carries an
  ``evidence_id``, run/turn/conversation identity, kind, statement,
  ``claim_source`` (exactly ``"verified"`` or ``"assumption"``), confidence,
  tz-aware UTC ``created_at`` and a provenance dict (tool_name,
  tool_call_id, exit_code, provider_id, model, phase).
- Strict verification rules: records are only ``verified`` when backed by
  tool exit codes, executor-written tool result records, test results,
  verifier output, or explicit user correction (``verified_by``). Model text
  alone (reflections, responses) can never be more than an ``assumption``.
- Staleness handling: a record is ``expired`` when ``rule_expiry`` passes or
  when a newer verified record about the same ``(phase, tool)`` pair has the
  opposite polarity. Superseding records are tagged with
  ``supersedes_evidence_id``; retrieval skips expired records and exposes the
  supersession chain for diagnostics.
- ``V5LearningEvidence`` mixin — ``collect_evidence(context, result, turn)``
  harvests verified outcomes from a finished turn (tool exit codes, failures,
  retries that eventually succeeded, verifier verdicts, user corrections),
  writes them through the store, nudges the meta-learning policy for verified
  outcomes only, and emits canonical ``learning.evidence`` /
  ``learning.policy`` events. It never re-logs turn replays (the replay JSONL
  is owned by ``V5Learning._log_turn_replay``) and never raises.

Every method is defensive and logs via ``self.logger``; a broken store can
never break the loop.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import re
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EVIDENCE_DIR_NAME = ".nexus_v5"
EVIDENCE_FILE_NAME = "evidence.jsonl"

EVIDENCE_KINDS = frozenset({
    "tool_outcome", "test_outcome", "failure", "retry_success",
    "user_correction", "verification", "reflection",
})

CLAIM_SOURCES = frozenset({"verified", "assumption"})

# Backing evidence that may justify claim_source="verified". Anything else
# (model text) is an assumption at most.
VERIFIED_BY_SOURCES = frozenset({
    "exit_code", "tool_result", "test_result", "verifier_output",
    "user_correction",
})

_POLARITIES = frozenset({"positive", "negative", "neutral"})

# Kinds whose polarity participates in supersession (reflection is neutral
# and can never supersede or be superseded).
_CONFLICT_KINDS = frozenset({
    "tool_outcome", "test_outcome", "failure", "retry_success",
    "user_correction", "verification",
})

_STATEMENT_LIMIT = 400
_TOOL_LIMIT = 80
_ID_LIMIT = 64
_MODEL_LIMIT = 160
_PHASE_LIMIT = 40
_ERROR_LIMIT = 200
_DEFAULT_CONFIDENCE = 0.5

_MAX_RECORDS = 2000          # compaction ceiling on the JSONL store
_MAX_HARVEST_PER_TURN = 12   # per-turn evidence ceiling (bounded growth)
_PROMPT_LIMIT = 1600         # hard ceiling on the LESSONS block
_DEFAULT_RETRIEVAL_TOP_K = 5

# Recency window for lesson scoring (14 days).
_SCORE_RECENCY_DAYS = 14.0
_SCORE_VERIFIED_BONUS = 0.25
_SCORE_PHASE_MATCH = 0.10
_SCORE_CONFIDENCE_WEIGHT = 0.5
_SCORE_RECENCY_WEIGHT = 0.15
_SCORE_TASK_WEIGHT = 0.20

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]{1,}")
_TOKEN_STOP = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "have", "was",
    "are", "not", "but", "you", "your", "use", "tool", "task", "work",
})


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, number))


def _bounded(value: Any, limit: int) -> str:
    return str(value or "")[: max(0, int(limit))]


def _parse_timestamp(value: Any) -> Optional[datetime.datetime]:
    """Parse an ISO string (or numeric epoch) into a tz-aware datetime."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _polarity_for(record: Dict[str, Any]) -> str:
    """Derive the durability polarity of a record from its kind and payload."""
    kind = str(record.get("kind") or "")
    if kind == "reflection":
        return "neutral"
    if kind == "user_correction":
        return "negative"
    if kind == "retry_success":
        return "positive"
    if kind == "failure":
        return "negative"
    status = str(record.get("status") or "").lower()
    if kind == "verification":
        if status in {"passed", "success"}:
            return "positive"
        if status in {"failed", "failure"}:
            return "negative"
        return "neutral"
    exit_code = record.get("exit_code")
    if isinstance(exit_code, int):
        return "positive" if exit_code == 0 else "negative"
    if status in {"passed", "success", "completed", "ok"}:
        return "positive"
    if status in {"failed", "failure", "error"}:
        return "negative"
    observed = record.get("observed_value")
    if isinstance(observed, (int, float)) and not isinstance(observed, bool):
        return "positive" if observed == 0 else "negative"
    return "neutral"


def _statement_tokens(record: Dict[str, Any]) -> set:
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    text = " ".join([
        str(record.get("statement") or ""),
        str(provenance.get("tool_name") or ""),
        str(provenance.get("phase") or ""),
    ]).lower()
    return {
        token for token in _TOKEN.findall(text)
        if token not in _TOKEN_STOP
    }


class LearningEvidenceStore:
    """Durable JSONL store of provenance-bearing learning evidence.

    Append-only with atomic rewrites for supersession tags and replay flags;
    guarded by a process-local lock so concurrent turns never interleave
    lines. Never raises on malformed input.
    """

    schema_version = 1

    def __init__(self, root_dir: str, path: Optional[str] = None):
        self.root_dir = str(root_dir or os.getcwd())
        self._path_override = path
        self._lock = threading.Lock()

    def _path(self) -> str:
        if self._path_override:
            return str(self._path_override)
        return os.path.join(self.root_dir, EVIDENCE_DIR_NAME, EVIDENCE_FILE_NAME)

    # ─────────────────────────────────────────────────────────────────────
    # WRITE PATH
    # ─────────────────────────────────────────────────────────────────────

    def record_verified(
        self,
        *,
        kind: str,
        statement: str,
        run_id: str = "",
        turn_id: str = "",
        conversation_id: str = "",
        tool_name: str = "",
        tool_call_id: str = "",
        exit_code: Optional[int] = None,
        provider_id: str = "",
        model: str = "",
        phase: str = "",
        confidence: float = 1.0,
        verified_by: Optional[List[str]] = None,
        observed_value: Any = None,
        expected_value: Any = None,
        rule_expiry: Any = None,
        failure_signature: str = "",
        status: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Record evidence only when it is backed by execution output."""
        return self.record(
            kind=kind, claim_source="verified", statement=statement,
            run_id=run_id, turn_id=turn_id, conversation_id=conversation_id,
            tool_name=tool_name, tool_call_id=tool_call_id, exit_code=exit_code,
            provider_id=provider_id, model=model, phase=phase,
            confidence=confidence, verified_by=verified_by,
            observed_value=observed_value, expected_value=expected_value,
            rule_expiry=rule_expiry, failure_signature=failure_signature,
            status=status,
        )

    def record_assumption(
        self,
        *,
        kind: str,
        statement: str,
        run_id: str = "",
        turn_id: str = "",
        conversation_id: str = "",
        tool_name: str = "",
        tool_call_id: str = "",
        exit_code: Optional[int] = None,
        provider_id: str = "",
        model: str = "",
        phase: str = "",
        confidence: float = _DEFAULT_CONFIDENCE,
        observed_value: Any = None,
        expected_value: Any = None,
        rule_expiry: Any = None,
        status: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Record a model-derived observation as an assumption, never verified."""
        return self.record(
            kind=kind, claim_source="assumption", statement=statement,
            run_id=run_id, turn_id=turn_id, conversation_id=conversation_id,
            tool_name=tool_name, tool_call_id=tool_call_id, exit_code=exit_code,
            provider_id=provider_id, model=model, phase=phase,
            confidence=confidence, verified_by=[],
            observed_value=observed_value, expected_value=expected_value,
            rule_expiry=rule_expiry, status=status,
        )

    def record(self, *, kind: str, claim_source: str, statement: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Validate and append one evidence record; returns it or None.

        ``claim_source="verified"`` is refused unless at least one entry in
        ``verified_by`` is a recognised execution-backed source, so unverified
        model claims can never be persisted as verified lessons.
        """
        kind = str(kind or "")
        claim_source = str(claim_source or "")
        if kind not in EVIDENCE_KINDS:
            logger.warning("[EVIDENCE] unknown kind %r ignored", kind)
            return None
        if claim_source not in CLAIM_SOURCES:
            logger.warning("[EVIDENCE] invalid claim_source %r ignored", claim_source)
            return None
        statement = str(statement or "").strip()[:_STATEMENT_LIMIT]
        if not statement:
            logger.warning("[EVIDENCE] empty statement ignored")
            return None
        verified_by = fields.get("verified_by") or []
        if claim_source == "verified" and not any(
            source in VERIFIED_BY_SOURCES for source in verified_by
        ):
            logger.warning(
                "[EVIDENCE] verified claim has no execution backing; refused "
                "(%s: %r)", kind, statement[:80]
            )
            return None

        exit_code = fields.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            exit_code = None
        created_at = _now_utc().isoformat()
        record: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "evidence_id": uuid.uuid4().hex,
            "run_id": _bounded(fields.get("run_id", ""), _ID_LIMIT),
            "turn_id": _bounded(fields.get("turn_id", ""), _ID_LIMIT),
            "conversation_id": _bounded(fields.get("conversation_id", ""), _ID_LIMIT),
            "kind": kind,
            "statement": statement,
            "claim_source": claim_source,
            "confidence": _clamp_confidence(fields.get("confidence", 1.0)),
            "provenance": {
                "tool_name": _bounded(fields.get("tool_name", ""), _TOOL_LIMIT),
                "tool_call_id": _bounded(fields.get("tool_call_id", ""), _ID_LIMIT),
                "exit_code": exit_code,
                "provider_id": _bounded(fields.get("provider_id", ""), _ID_LIMIT),
                "model": _bounded(fields.get("model", ""), _MODEL_LIMIT),
                "phase": _bounded(fields.get("phase", ""), _PHASE_LIMIT),
            },
            "created_at": created_at,
            "observed_value": fields.get("observed_value"),
            "expected_value": fields.get("expected_value"),
            "replayed": False,
            "polarity": _polarity_for({
                **fields,
                "kind": kind,
                "exit_code": exit_code,
                "status": fields.get("status", ""),
            }),
            "verified_by": sorted(
                {source for source in verified_by if source in VERIFIED_BY_SOURCES}
            ),
            "rule_expiry": _parse_timestamp(fields.get("rule_expiry")).isoformat()
            if _parse_timestamp(fields.get("rule_expiry")) is not None else None,
            "supersedes_evidence_id": [],
            "superseded_by": None,
            "failure_signature": _bounded(fields.get("failure_signature", ""), 32),
        }
        if claim_source == "assumption":
            # Assumption records are already refused the verified flag, but a
            # caller passing verified_by must not be able to smuggle it.
            record["verified_by"] = []
        try:
            with self._lock:
                existing = self.load_all(limit=_MAX_RECORDS)
                self._apply_supersession(existing, record)
                existing.append(record)
                self._rewrite(existing)
        except Exception as exc:
            logger.warning("[EVIDENCE] store write failed: %s", exc)
            return None
        return record

    def _apply_supersession(
        self, records: List[Dict[str, Any]], new_record: Dict[str, Any]
    ) -> None:
        """Tag opposite-polarity verified conflicts as superseded.

        A newer verified record about the same (phase, tool) pair with the
        opposite polarity supersedes older records: the new record is tagged
        with ``supersedes_evidence_id`` and each old record with
        ``superseded_by``. Only records with polarity (never neutral) and
        conflict-capable kinds participate.
        """
        if new_record.get("claim_source") != "verified":
            return
        new_id = new_record.get("evidence_id", "")
        new_phase = _bounded(
            (new_record.get("provenance") or {}).get("phase"), _PHASE_LIMIT
        )
        new_tool = _bounded(
            (new_record.get("provenance") or {}).get("tool_name"), _TOOL_LIMIT
        )
        new_polarity = new_record.get("polarity")
        if new_polarity not in _POLARITIES or new_polarity == "neutral":
            return
        now = _now_utc()
        conflicts = []
        for old in records:
            if not isinstance(old, dict):
                continue
            if old.get("evidence_id") == new_id:
                continue
            if old.get("claim_source") != "verified":
                continue
            if old.get("kind") not in _CONFLICT_KINDS:
                continue
            if old.get("superseded_by"):
                continue
            old_polarity = old.get("polarity")
            if old_polarity not in _POLARITIES or old_polarity == "neutral":
                continue
            if old_polarity == new_polarity:
                continue
            provenance = old.get("provenance")
            if not isinstance(provenance, dict):
                continue
            old_phase = _bounded(provenance.get("phase"), _PHASE_LIMIT)
            old_tool = _bounded(provenance.get("tool_name"), _TOOL_LIMIT)
            if (old_phase, old_tool) != (new_phase, new_tool):
                continue
            if self._rule_expired(old, now):
                continue
            conflicts.append(old)
        if conflicts:
            new_record["supersedes_evidence_id"] = [
                str(item.get("evidence_id") or "") for item in conflicts
            ]
            for item in conflicts:
                item["superseded_by"] = new_id

    # ─────────────────────────────────────────────────────────────────────
    # READ PATH
    # ─────────────────────────────────────────────────────────────────────

    def load_all(self, limit: int = _MAX_RECORDS) -> List[Dict[str, Any]]:
        """Read records oldest-first; malformed lines are skipped. Never raises."""
        try:
            path = self._path()
            if not os.path.isfile(path):
                return []
            records: List[Dict[str, Any]] = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        records.append(parsed)
            ceiling = max(0, int(limit or _MAX_RECORDS))
            return records[:ceiling]
        except Exception as exc:
            logger.warning("[EVIDENCE] store load failed: %s", exc)
            return []

    def get(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        for record in self.load_all():
            if str(record.get("evidence_id") or "") == str(evidence_id):
                return record
        return None

    def _rewrite(self, records: List[Dict[str, Any]]) -> None:
        path = self._path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as fh:
            for record in records[-_MAX_RECORDS:]:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        os.replace(temporary, path)

    def _rule_expired(self, record: Dict[str, Any], now: datetime.datetime) -> bool:
        expiry = _parse_timestamp(record.get("rule_expiry"))
        return expiry is not None and now > expiry

    def is_expired(self, record: Any, now: Optional[datetime.datetime] = None) -> bool:
        """True when the record's rule_expiry passed or it was superseded."""
        if not isinstance(record, dict):
            return True
        if record.get("superseded_by"):
            return True
        return self._rule_expired(record, now or _now_utc())

    def mark_replayed(self, evidence_id: str) -> bool:
        """Persist ``replayed=True`` so diagnostics can show what was surfaced."""
        try:
            with self._lock:
                records = self.load_all()
                updated = False
                for record in records:
                    if str(record.get("evidence_id") or "") == str(evidence_id):
                        if not record.get("replayed"):
                            record["replayed"] = True
                            updated = True
                        break
                if updated:
                    self._rewrite(records)
                return updated
        except Exception as exc:
            logger.warning("[EVIDENCE] mark_replayed failed: %s", exc)
            return False

    def _epoch(self, record: Dict[str, Any]) -> float:
        parsed = _parse_timestamp(record.get("created_at"))
        return parsed.timestamp() if parsed is not None else 0.0

    def _lesson_score(
        self, record: Dict[str, Any], phase: str, task_summary: str,
        now: datetime.datetime,
    ) -> float:
        """Rank lessons by confidence, verified status, recency and task fit."""
        score = _clamp_confidence(record.get("confidence")) * _SCORE_CONFIDENCE_WEIGHT
        if record.get("claim_source") == "verified":
            score += _SCORE_VERIFIED_BONUS
        created = _parse_timestamp(record.get("created_at"))
        if created is not None:
            age_days = max(0.0, (now - created).total_seconds() / 86400.0)
            score += _SCORE_RECENCY_WEIGHT * math.exp(-age_days / _SCORE_RECENCY_DAYS)
        provenance = record.get("provenance")
        if isinstance(provenance, dict):
            if phase and str(provenance.get("phase") or "") == str(phase):
                score += _SCORE_PHASE_MATCH
            if task_summary and str(provenance.get("tool_name") or "").lower() in str(task_summary).lower():
                score += _SCORE_PHASE_MATCH * 0.5
        if task_summary:
            query_tokens = {
                token for token in _TOKEN.findall(str(task_summary).lower())
                if token not in _TOKEN_STOP
            }
            if query_tokens:
                record_tokens = _statement_tokens(record)
                overlap = len(query_tokens & record_tokens) / len(query_tokens)
                score += _SCORE_TASK_WEIGHT * min(1.0, overlap)
        return score

    def retrieve_lessons(
        self,
        run_id: str = "",
        phase: str = "",
        task_summary: str = "",
        top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
    ) -> List[Dict[str, Any]]:
        """Return the top-k non-expired evidence records for the current task.

        Each item is ``{"record", "score", "supersedes", "superseded_by"}``:
        ``supersedes`` lists the evidence ids this record replaced, and
        ``superseded_by`` is the id that replaced it (expired records are
        excluded, so it is normally None). Ordered by confidence, verified
        status, recency and task relevance. Never raises.
        """
        now = _now_utc()
        try:
            eligible = [
                record for record in self.load_all()
                if not self.is_expired(record, now)
            ]
            scored = [
                (self._lesson_score(record, phase, task_summary, now), record)
                for record in eligible
            ]
            scored.sort(key=lambda pair: (
                -pair[0],
                -self._epoch(pair[1]),
                str(pair[1].get("evidence_id") or ""),
            ))
            items = []
            for score, record in scored[: max(0, int(top_k or _DEFAULT_RETRIEVAL_TOP_K))]:
                items.append({
                    "record": record,
                    "score": round(score, 4),
                    "supersedes": list(record.get("supersedes_evidence_id") or []),
                    "superseded_by": record.get("superseded_by"),
                })
            return items
        except Exception as exc:
            logger.warning("[EVIDENCE] retrieve_lessons failed: %s", exc)
            return []


class V5LearningEvidence:
    """Mixin: harvest verified turn outcomes into the durable evidence store.

    Mirrors the ``V5Learning`` mixin style: defensive, never raises, never
    touches the kernel, and never re-logs turn replays.
    """

    def _evidence_store(self) -> Optional[LearningEvidenceStore]:
        """Lazily create the per-root durable store (None without root_dir)."""
        root = getattr(self, "root_dir", None)
        if not root:
            return None
        store = getattr(self, "_learning_evidence_store", None)
        if store is None:
            store = LearningEvidenceStore(root)
            self._learning_evidence_store = store
        return store

    def _evidence_context_ids(self) -> tuple:
        run_id = str(
            getattr(self, "_current_turn_id", "") or getattr(self, "session_id", "") or "run"
        )[:_ID_LIMIT]
        conversation_id = str(
            getattr(getattr(self, "runtime", None), "conversation_id", "")
            or getattr(self, "session_id", "") or ""
        )[:_ID_LIMIT]
        return run_id, conversation_id

    def _evidence_provider(self) -> tuple:
        runtime = getattr(self, "runtime", None)
        provider_id = ""
        model = ""
        if runtime is not None:
            provider_id = str(getattr(runtime, "provider_id", "") or "")[:_ID_LIMIT]
            model = str(getattr(runtime, "model", "") or "")[:_MODEL_LIMIT]
        return provider_id, model

    def _evidence_phase(self, turn: Any) -> str:
        state = getattr(turn, "state", None) if turn is not None else None
        if state is None:
            return ""
        if hasattr(state, "value"):
            value = str(state.value)
        else:
            value = str(state)
        return value[: _PHASE_LIMIT]

    def _harvest_actions(
        self, result: Dict[str, Any], run_id: str, conversation_id: str,
        provider_id: str, model: str, phase: str, turn_id: str,
    ) -> List[Dict[str, Any]]:
        """Turn executor-written action records into verified evidence.

        Every action dict is written by the tool executor (never the model),
        so its terminal success/error/exit_code fields count as tool output.
        Successful calls without an exit code are intentionally skipped to
        keep the store focused on lessons, not mundane completions.
        """
        actions = (result.get("actions") or []) if isinstance(result, dict) else []
        harvested: List[Dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            tool = str(action.get("tool") or action.get("name") or "")[:_TOOL_LIMIT]
            if not tool:
                continue
            tool_call_id = str(action.get("call_id") or "")[:_ID_LIMIT]
            exit_code = action.get("exit_code")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                exit_code = None
            success = bool(action.get("success"))
            error = str(action.get("error") or "")[:_ERROR_LIMIT]
            if bool(action.get("repaired")):
                harvested.append({
                    "kind": "retry_success",
                    "statement": f"{tool} succeeded after a retried attempt",
                    "tool_name": tool, "tool_call_id": tool_call_id,
                    "exit_code": exit_code, "phase": phase,
                    "confidence": 1.0, "verified_by": ["tool_result"],
                    "observed_value": error or None, "expected_value": None,
                    "failure_signature": "", "status": "success",
                })
            elif isinstance(exit_code, int):
                harvested.append({
                    "kind": "tool_outcome",
                    "statement": (
                        f"{tool} exit code {exit_code}"
                        if exit_code == 0
                        else f"{tool} failed with exit code {exit_code}"
                    ),
                    "tool_name": tool, "tool_call_id": tool_call_id,
                    "exit_code": exit_code, "phase": phase,
                    "confidence": 1.0, "verified_by": ["exit_code"],
                    "observed_value": exit_code, "expected_value": 0,
                    "failure_signature": "" if exit_code == 0 else str(
                        action.get("failure_signature") or ""
                    )[:_ID_LIMIT],
                    "status": "success" if exit_code == 0 else "failed",
                })
            elif not success:
                harvested.append({
                    "kind": "failure",
                    "statement": f"{tool} failed: {error or 'no error detail'}",
                    "tool_name": tool, "tool_call_id": tool_call_id,
                    "exit_code": None, "phase": phase,
                    "confidence": 1.0, "verified_by": ["tool_result"],
                    "observed_value": error or None, "expected_value": None,
                    "failure_signature": str(action.get("failure_signature") or "")[:_ID_LIMIT],
                    "status": "failed",
                })
        return harvested

    def _harvest_verification(
        self, result: Dict[str, Any], run_id: str, conversation_id: str,
        provider_id: str, model: str, phase: str, turn_id: str,
    ) -> List[Dict[str, Any]]:
        verification = result.get("verification") if isinstance(result, dict) else None
        if not isinstance(verification, dict):
            return []
        success = bool(verification.get("success"))
        failed_actions = int(verification.get("failed_actions", 0) or 0)
        return [{
            "kind": "verification",
            "statement": (
                "Verification passed"
                if success else f"Verification failed: {failed_actions} action(s) failed"
            ),
            "tool_name": "", "tool_call_id": "", "exit_code": None, "phase": phase,
            "confidence": 1.0, "verified_by": ["verifier_output"],
            "observed_value": str(verification.get("status") or "")[:_ERROR_LIMIT],
            "expected_value": "passed",
            "failure_signature": "",
            "status": "passed" if success else "failed",
        }]

    def _harvest_user_correction(
        self, result: Dict[str, Any], run_id: str, conversation_id: str,
        provider_id: str, model: str, phase: str, turn_id: str,
    ) -> List[Dict[str, Any]]:
        correction = result.get("user_correction") if isinstance(result, dict) else None
        if not correction:
            return []
        if isinstance(correction, dict):
            detail = str(correction.get("message") or correction.get("feedback") or "")[: _ERROR_LIMIT]
        else:
            detail = ""
        return [{
            "kind": "user_correction",
            "statement": f"User corrected the agent's approach: {detail or 'follow-up instruction'}",
            "tool_name": str(correction.get("tool") or "")[:_TOOL_LIMIT]
            if isinstance(correction, dict) else "",
            "tool_call_id": str(correction.get("tool_call_id") or "")[:_ID_LIMIT]
            if isinstance(correction, dict) else "",
            "exit_code": None, "phase": phase,
            "confidence": 1.0, "verified_by": ["user_correction"],
            "observed_value": detail or None, "expected_value": None,
            "failure_signature": "",
        }]

    def _harvest_reflection(
        self, result: Dict[str, Any], run_id: str, conversation_id: str,
        provider_id: str, model: str, phase: str, turn_id: str,
    ) -> List[Dict[str, Any]]:
        """Reflection text is model output: assumption at most, never verified."""
        reflection = result.get("reflection") if isinstance(result, dict) else None
        if not isinstance(reflection, dict):
            return []
        signals = []
        for key in ("root_causes", "improvements"):
            items = reflection.get(key)
            if isinstance(items, list):
                for item in items[:1]:
                    text = str(item or "").strip()[:_STATEMENT_LIMIT]
                    if text:
                        signals.append(f"{key.replace('_', ' ')}: {text}")
        if not signals:
            return []
        return [{
            "kind": "reflection",
            "statement": signals[0],
            "tool_name": "", "tool_call_id": "", "exit_code": None, "phase": phase,
            "confidence": _DEFAULT_CONFIDENCE, "verified_by": [],
            "observed_value": None, "expected_value": None,
            "failure_signature": "",
        }]

    async def collect_evidence(self, context, result, turn) -> int:
        """Harvest verified outcomes from one finished turn into the store.

        Also nudges the meta-learning policy for verified tool outcomes and
        emits canonical ``learning.evidence`` / ``learning.policy`` events.
        Returns the number of records written; never raises.
        """
        store = self._evidence_store()
        if store is None:
            return 0
        if not isinstance(result, dict):
            return 0
        try:
            run_id, conversation_id = self._evidence_context_ids()
            provider_id, model = self._evidence_provider()
            phase = self._evidence_phase(turn)
            turn_id = str(
                getattr(turn, "turn_id", "") or getattr(self, "_current_turn_id", "") or ""
            )[:_ID_LIMIT]

            candidates: List[Dict[str, Any]] = []
            candidates.extend(self._harvest_actions(
                result, run_id, conversation_id, provider_id, model, phase, turn_id
            ))
            candidates.extend(self._harvest_verification(
                result, run_id, conversation_id, provider_id, model, phase, turn_id
            ))
            candidates.extend(self._harvest_user_correction(
                result, run_id, conversation_id, provider_id, model, phase, turn_id
            ))
            candidates.extend(self._harvest_reflection(
                result, run_id, conversation_id, provider_id, model, phase, turn_id
            ))

            recorded: List[Dict[str, Any]] = []
            for candidate in candidates[:_MAX_HARVEST_PER_TURN]:
                claim_source = "verified" if candidate.get("verified_by") else "assumption"
                if claim_source == "verified":
                    record = store.record_verified(
                        kind=candidate["kind"], statement=candidate["statement"],
                        run_id=run_id, turn_id=turn_id, conversation_id=conversation_id,
                        tool_name=candidate.get("tool_name", ""),
                        tool_call_id=candidate.get("tool_call_id", ""),
                        exit_code=candidate.get("exit_code"),
                        provider_id=provider_id, model=model, phase=phase,
                        confidence=candidate.get("confidence", 1.0),
                        verified_by=candidate.get("verified_by", []),
                        observed_value=candidate.get("observed_value"),
                        expected_value=candidate.get("expected_value"),
                        failure_signature=candidate.get("failure_signature", ""),
                        status=candidate.get("status", ""),
                    )
                else:
                    record = store.record_assumption(
                        kind=candidate["kind"], statement=candidate["statement"],
                        run_id=run_id, turn_id=turn_id, conversation_id=conversation_id,
                        provider_id=provider_id, model=model, phase=phase,
                        confidence=candidate.get("confidence", _DEFAULT_CONFIDENCE),
                        observed_value=candidate.get("observed_value"),
                        expected_value=candidate.get("expected_value"),
                        status=candidate.get("status", ""),
                    )
                if record is not None:
                    recorded.append(record)

            policy_nudges: Dict[str, Any] = {}
            for record in recorded:
                if record.get("claim_source") != "verified":
                    continue
                nudge = self._nudge_policy_from_evidence(record)
                if nudge:
                    policy_nudges[record["evidence_id"]] = {
                        "evidence": record,
                        "nudge": nudge,
                    }
            await self._emit_learning_events(recorded, policy_nudges)
            if recorded:
                self.logger.info(
                    "[LEARNING] evidence: %d record(s) harvested for turn %s",
                    len(recorded), turn_id or run_id,
                )
            return len(recorded)
        except Exception as exc:
            self.logger.warning(f"[LEARNING] evidence collection failed: {exc}")
            return 0

    def _nudge_policy_from_evidence(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Nudge the persisted meta-learning policy from verified evidence only.

        Assumption records never reach ``on_verified_evidence`` here; the
        meta layer double-checks ``claim_source == "verified"`` anyway.
        """
        meta = getattr(self, "meta_learning", None) or getattr(self, "_meta_learning", None)
        if meta is None:
            return {}
        nudger = getattr(meta, "on_verified_evidence", None)
        if not callable(nudger):
            return {}
        try:
            nudge = nudger(evidence)
            return dict(nudge or {})
        except Exception as exc:
            self.logger.debug(f"[LEARNING] policy nudge skipped: {exc}")
            return {}

    async def _emit_learning_events(
        self, records: List[Dict[str, Any]], policy_nudges: Dict[str, Any]
    ) -> None:
        """Best-effort emission; a broken emitter must never break the loop."""
        emit = getattr(self, "_emit_learning_event", None)
        if not callable(emit):
            return
        for record in records:
            try:
                await emit("learning.evidence", evidence=record)
            except Exception as exc:
                self.logger.debug(f"[LEARNING] evidence event skipped: {exc}")
        for entry in policy_nudges.values():
            try:
                await emit(
                    "learning.policy", evidence=entry["evidence"], policy=entry["nudge"]
                )
            except Exception as exc:
                self.logger.debug(f"[LEARNING] policy event skipped: {exc}")

    def _evidence_lessons_prompt(
        self, task_summary: str = "", top_k: int = 4, phase: str = ""
    ) -> str:
        """Render a compact model-readable block of prior verified lessons.

        Only ``verified`` lessons are surfaced (never assumptions), each with
        its evidence id so the model can trace the claim. Retrieved records
        are marked ``replayed`` for diagnostics. Bounded; "" when nothing is
        available; never raises.
        """
        store = self._evidence_store()
        if store is None:
            return ""
        try:
            run_id, _conversation_id = self._evidence_context_ids()
            lessons = store.retrieve_lessons(
                run_id=run_id, phase=phase, task_summary=task_summary, top_k=top_k
            )
            lines = []
            for item in lessons:
                record = item.get("record")
                if not isinstance(record, dict):
                    continue
                if record.get("claim_source") != "verified":
                    continue
                evidence_id = str(record.get("evidence_id") or "")[:8]
                kind = str(record.get("kind") or "lesson")
                statement = str(record.get("statement") or "")[:200]
                tool = (record.get("provenance") or {}).get("tool_name") or ""
                label = f"{tool}: " if tool else ""
                lines.append(f"- [{kind}] {label}{statement} (evidence: {evidence_id})")
                store.mark_replayed(str(record.get("evidence_id") or ""))
            if not lines:
                return ""
            block = "LESSONS FROM VERIFIED OUTCOMES:\n" + "\n".join(lines)
            if len(block) > _PROMPT_LIMIT:
                block = block[:_PROMPT_LIMIT].rstrip() + "\n...[truncated]"
            return block
        except Exception as exc:
            self.logger.debug(f"[LEARNING] lessons prompt failed: {exc}")
            return ""

    def retrieve_lessons(
        self,
        run_id: str = "",
        phase: str = "",
        task_summary: str = "",
        top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
    ) -> List[Dict[str, Any]]:
        """Passthrough to the durable store; the mixin's public retrieval API."""
        store = self._evidence_store()
        if store is None:
            return []
        return store.retrieve_lessons(
            run_id=run_id or (getattr(self, "_current_turn_id", "") or getattr(self, "session_id", "")),
            phase=phase, task_summary=task_summary, top_k=top_k,
        )


__all__ = [
    "CLAIM_SOURCES",
    "EVIDENCE_KINDS",
    "VERIFIED_BY_SOURCES",
    "LearningEvidenceStore",
    "V5LearningEvidence",
]
