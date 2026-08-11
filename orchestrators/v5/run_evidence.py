"""Durable, redacted evidence bundles for provider/loop comparisons."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from providers.reliability import redact_secrets
from .events import summarize_work_events


def _slug(value: Any, fallback: str = "unknown") -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return (text[:80] or fallback)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, tuple):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return redact_secrets(value)[:4000]
    return value


def _successful_provider(attempts: Iterable[Dict[str, Any]]) -> str:
    last = ""
    for attempt in attempts:
        provider = str(attempt.get("provider_id") or "")
        if provider:
            last = provider
        if str(attempt.get("status") or "") == "success":
            return provider or last
    return last


def _bounded_text(value: Any, limit: int = 1200) -> str:
    return str(value or "")[:limit]


def _canonical_event_summary(events: Any) -> list[Dict[str, Any]]:
    """Retain canonical event identity without copying event payloads."""
    if not isinstance(events, list):
        return []
    summaries = []
    for event in events[-128:]:
        if not isinstance(event, dict):
            continue
        item = {
            "event_id": _bounded_text(event.get("event_id") or event.get("id"), 160),
            "type": _bounded_text(event.get("type") or event.get("event_type"), 80),
            "status": _bounded_text(event.get("status"), 32),
            "sequence": event.get("sequence"),
            "parent_id": _bounded_text(event.get("parent_id"), 160),
            "related_tool": _bounded_text(event.get("related_tool") or event.get("tool"), 120),
        }
        if item["event_id"] or item["type"]:
            summaries.append(item)
    return summaries


_ARTIFACT_STATUSES = {"present", "missing", "invalid", "unlinked", "ambiguous"}


def _artifact_digest(path_value: Any, root_dir: str = "") -> str:
    """Return a content identity for a readable artifact, or an empty string."""
    path = _artifact_path(path_value, root_dir)
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return ""


def _artifact_path(value: Any, root_dir: str = "") -> Path | None:
    """Resolve an evidence path without requiring it to exist."""
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    if not path.is_absolute() and root_dir:
        path = Path(root_dir) / path
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _replay_record_digest(record: Dict[str, Any]) -> str:
    """Recompute the digest over the replay record's identity-bearing fields."""
    payload = dict(record)
    payload.pop("record_sha256", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _replay_status(path_value: Any, *, root_dir: str = "", entry_id: str = "",
                   record_sha256: str = "", turn_id: str = "", session_id: str = "") -> str:
    """Classify a JSONL replay path using stable identity when available."""
    path = _artifact_path(path_value, root_dir)
    if path is None or not path.exists():
        return "missing"
    if not path.is_file():
        return "invalid"
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                return "invalid"
            records.append(record)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "invalid"
    if not records:
        return "unlinked"
    matches = []
    invalid_digest = False
    for record in records:
        if entry_id and str(record.get("entry_id") or "") != entry_id:
            continue
        if turn_id and str(record.get("turn_id") or "") != turn_id:
            continue
        if session_id and str(record.get("session_id") or "") != session_id:
            continue
        # A positive status requires at least one identity field to be linked.
        if entry_id or turn_id or session_id:
            if record_sha256:
                if str(record.get("record_sha256") or "") != record_sha256:
                    continue
                if _replay_record_digest(record) != record_sha256:
                    invalid_digest = True
                    continue
            matches.append(record)
    if invalid_digest:
        return "invalid"
    if len(matches) == 1:
        return "present"
    if len(matches) > 1:
        return "ambiguous"
    return "unlinked"


def _checkpoint_status(path_value: Any, *, root_dir: str = "", turn_id: str = "",
                       session_id: str = "") -> str:
    """Classify one checkpoint JSON file and verify its run identity."""
    path = _artifact_path(path_value, root_dir)
    if path is None or not path.exists():
        return "missing"
    if not path.is_file():
        return "invalid"
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "invalid"
    if not isinstance(checkpoint, dict):
        return "invalid"
    checkpoint_turn = str(checkpoint.get("turn_id") or "")
    checkpoint_session = str(checkpoint.get("session") or checkpoint.get("session_id") or "")
    if turn_id and checkpoint_turn and checkpoint_turn != turn_id:
        return "unlinked"
    if session_id and checkpoint_session and checkpoint_session != session_id:
        return "unlinked"
    # A checkpoint without the identity expected by the evidence is not safely linked.
    if turn_id and not checkpoint_turn:
        return "unlinked"
    if session_id and not checkpoint_session:
        return "unlinked"
    return "present"


def _overall_status(statuses: Iterable[str]) -> str:
    statuses = list(statuses)
    if not statuses:
        return "missing"
    for status in ("ambiguous", "invalid", "unlinked", "missing"):
        if status in statuses:
            return status
    return "present"


def _trace_summary(payload: Dict[str, Any], events: Any = None, *, session_id: str = "",
                   root_dir: str = "") -> Dict[str, Any]:
    """Normalize Nexus trace artifacts at the evidence boundary."""
    replay = payload.get("replay") if isinstance(payload.get("replay"), dict) else {}
    checkpoints = payload.get("checkpoints")
    if not isinstance(checkpoints, list):
        checkpoints = payload.get("checkpoint_paths")
    if not isinstance(checkpoints, list):
        checkpoints = [payload.get("checkpoint_path") or payload.get("resumed_from_checkpoint")]
    replay_path = _bounded_text(replay.get("path") or payload.get("replay_path"), 500)
    turn_id = _bounded_text(payload.get("turn_id"), 120)
    replay_entry_id = _bounded_text(replay.get("entry_id") or payload.get("replay_entry_id"), 160)
    replay_record_sha256 = _bounded_text(replay.get("record_sha256") or payload.get("replay_record_sha256"), 64)
    replay_status = _replay_status(
        replay_path, root_dir=root_dir, entry_id=replay_entry_id,
        record_sha256=replay_record_sha256,
        turn_id=turn_id, session_id=_bounded_text(session_id, 120),
    )
    checkpoint_values = [_bounded_text(item, 500) for item in checkpoints if item]
    checkpoint_artifacts = [
        {
            "path": path,
            "status": _checkpoint_status(
                path, root_dir=root_dir, turn_id=turn_id,
                session_id=_bounded_text(session_id, 120),
            ),
            "sha256": _artifact_digest(path, root_dir),
        }
        for path in checkpoint_values[-32:]
    ]
    # ``events`` is the raw emitter input.  Existing callers may provide an
    # already-safe ``canonical_events`` list; keep that legacy shape intact.
    captured = summarize_work_events(events) if isinstance(events, list) else None
    canonical_events = _canonical_event_summary(payload.get("canonical_events"))
    if captured is not None:
        canonical_events = captured["events"]
    event_ids = [
            _bounded_text(item, 160) for item in (payload.get("canonical_event_ids") or []) if item
        ]
    if captured is not None:
        event_ids.extend(item["event_id"] for item in canonical_events if item.get("event_id"))
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    verifier_event_id = _bounded_text(
        verification.get("event_id") or payload.get("verification_event_id"), 160
    )
    joins = {
        "session_id": _bounded_text(session_id, 120),
        "turn_id": turn_id,
        "verifier_event_id": verifier_event_id,
        "replay_entry_id": replay_entry_id,
        "replay_record_sha256": replay_record_sha256,
        "checkpoint_artifacts": [
            {"path": item["path"], "status": item["status"], "sha256": item.get("sha256", "")}
            for item in checkpoint_artifacts
        ],
    }
    return {
        "canonical_event_ids": list(dict.fromkeys(event_ids))[-128:],
        "canonical_events": canonical_events[-128:],
        "replay": {
            "path": replay_path,
            "logged": bool(replay.get("logged", payload.get("replay_logged", False))),
            "entry_id": replay_entry_id,
            "record_sha256": replay_record_sha256,
            "status": replay_status,
            "artifact_status": replay_status,
        },
        # Kept as a compatibility alias for existing consumers.
        "replay_path": replay_path,
        "checkpoint_paths": checkpoint_values[-32:],
        "checkpoints": checkpoint_artifacts,
        "verifier_event_id": verifier_event_id,
        "joins": joins,
        "artifact_status": _overall_status(
            [replay_status] + [item["status"] for item in checkpoint_artifacts]
        ),
    }


def _refresh_trace_artifact_status(evidence: Dict[str, Any], root_dir: str) -> None:
    """Resolve relative artifact paths immediately before durable persistence."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get("trace"), dict):
        return
    trace = evidence["trace"]
    replay = trace.get("replay") if isinstance(trace.get("replay"), dict) else {}
    turn_id = _bounded_text(evidence.get("turn_id"), 120)
    session_id = _bounded_text(evidence.get("session_id"), 120)
    status = _replay_status(
        replay.get("path"), root_dir=root_dir,
        entry_id=_bounded_text(replay.get("entry_id"), 160),
        record_sha256=_bounded_text(replay.get("record_sha256"), 64),
        turn_id=turn_id, session_id=session_id,
    )
    replay["status"] = status
    replay["artifact_status"] = status
    replay["sha256"] = _artifact_digest(replay.get("path"), root_dir) if status == "present" else ""
    trace["replay"] = replay
    artifacts = []
    for item in trace.get("checkpoints") or []:
        if not isinstance(item, dict):
            continue
        path = _bounded_text(item.get("path"), 500)
        status = _checkpoint_status(path, root_dir=root_dir, turn_id=turn_id,
                                    session_id=session_id)
        artifacts.append({
            "path": path,
            "status": status,
            "sha256": _artifact_digest(path, root_dir) if status == "present" else "",
        })
    trace["checkpoints"] = artifacts
    verification = evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
    trace["verifier_event_id"] = _bounded_text(verification.get("event_id"), 160)
    joins = trace.get("joins") if isinstance(trace.get("joins"), dict) else {}
    joins.update({
        "session_id": _bounded_text(evidence.get("session_id"), 120),
        "turn_id": _bounded_text(evidence.get("turn_id"), 120),
        "verifier_event_id": trace["verifier_event_id"],
        "replay_entry_id": _bounded_text(replay.get("entry_id"), 160),
        "replay_record_sha256": _bounded_text(replay.get("record_sha256"), 64),
        "checkpoint_artifacts": artifacts,
    })
    trace["joins"] = joins
    trace["artifact_status"] = _overall_status(
        [replay.get("status", "missing")] + [item["status"] for item in artifacts]
    )


def _refresh_durable_verification(evidence: Dict[str, Any], root_dir: str) -> None:
    """Project the cross-process verifier state when its ledger exists."""
    verification = evidence.get("verification") if isinstance(evidence, dict) else None
    if not isinstance(verification, dict):
        return
    state_path = Path(root_dir) / ".nexus_v5" / "verifier_state.json"
    if not state_path.is_file():
        return
    try:
        from .verification_state import VerifierStateStore

        state = VerifierStateStore(state_path).get(
            str(evidence.get("session_id") or "default"), root_dir
        )
        verification.update({
            "durable_status": str(state.get("status") or "unverified")[:24],
            "verifier_id": str(state.get("verifier_id") or "")[:64],
            "event_id": str(state.get("last_event_id") or "")[:64],
            "verified_at": state.get("verified_at"),
            "last_edit_at": state.get("stale_at"),
            "changed_paths": list(state.get("changed_paths") or [])[:200],
        })
    except Exception:
        return


def _verification_summary(value: Any) -> Dict[str, Any]:
    """Keep verifier verdicts useful while excluding verbose evidence blobs."""
    if not isinstance(value, dict):
        return {}
    summary = {}
    for key in ("status", "durable_status", "verifier_id", "event_id", "verified_at", "last_edit_at",
                "success", "evidence_ok", "verified", "verified_actions", "failed_actions",
                "calls_executed", "verifier", "reason"):
        if key in value:
            item = value[key]
            if isinstance(item, list):
                summary[key] = [_bounded_text(entry, 300) for entry in item[:32]]
            elif isinstance(item, (bool, int, float)):
                summary[key] = item
            else:
                summary[key] = _bounded_text(item, 500)
    anomalies = value.get("anomalies")
    if isinstance(anomalies, list):
        summary["anomalies"] = [_bounded_text(entry, 300) for entry in anomalies[:32]]
    if isinstance(value.get("changed_paths"), list):
        summary["changed_paths"] = [_bounded_text(path, 500) for path in value["changed_paths"][:200]]
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        summary["freshness"] = {
            "status": _bounded_text(freshness.get("status"), 24),
            "evidence_id": _bounded_text(freshness.get("evidence_id"), 64),
            "checked_at": freshness.get("checked_at"),
            "artifacts": [
                {
                    "path": _bounded_text(item.get("path"), 500),
                    "sha256": _bounded_text(item.get("sha256"), 64),
                    "status": _bounded_text(item.get("status"), 24),
                }
                for item in (freshness.get("artifacts") or [])[:32]
                if isinstance(item, dict)
            ],
        }
    return summary


def _trajectory_summary(payload: Dict[str, Any], model: str, completed: bool) -> Dict[str, Any]:
    """Describe Hermes trajectory compatibility without persisting a transcript."""
    source = payload.get("conversations") or payload.get("messages") or payload.get("trajectory")
    messages = source if isinstance(source, list) else []
    role_counts: Dict[str, int] = {}
    tool_call_ids = []
    for message in messages[-128:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("from") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and (call.get("id") or call.get("tool_call_id")):
                tool_call_ids.append(_bounded_text(call.get("id") or call.get("tool_call_id"), 160))
        if message.get("tool_call_id"):
            tool_call_ids.append(_bounded_text(message.get("tool_call_id"), 160))
    return {
        "format": "hermes-sharegpt-v1",
        "model": _bounded_text(model, 160),
        "completed": bool(completed),
        "message_count": len(messages),
        "role_counts": role_counts,
        "tool_call_ids": list(dict.fromkeys(tool_call_ids))[-128:],
    }


def build_hermes_trajectory(messages: Any, *, model: str = "", completed: bool = False,
                            user_query: str = "") -> Dict[str, Any]:
    """Convert Nexus messages to Hermes' bounded ShareGPT trajectory envelope."""
    source = messages if isinstance(messages, list) else []
    conversations = []
    if user_query:
        conversations.append({"from": "human", "value": _bounded_text(user_query, 4000)})
    for message in source[:128]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("from") or "").lower()
        sender = {"system": "system", "user": "human", "human": "human",
                  "assistant": "gpt", "gpt": "gpt", "tool": "tool"}.get(role)
        if not sender:
            continue
        value = message.get("content", message.get("value", ""))
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        value = _bounded_text(value, 4000)
        if sender == "gpt":
            tool_calls = message.get("tool_calls") or []
            if isinstance(tool_calls, list):
                for call in tool_calls[:16]:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") if isinstance(call.get("function"), dict) else call
                    name = _bounded_text(function.get("name"), 120)
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except (TypeError, ValueError):
                            arguments = _bounded_text(arguments, 1000)
                    value += "\n<tool_call>\n" + json.dumps(
                        {"name": name, "arguments": arguments},
                        ensure_ascii=False, default=str,
                    )[:1600] + "\n</tool_call>"
        if sender == "gpt" and "<think>" not in value:
            value = "<think>\n</think>\n" + value
        if sender == "tool" and message.get("tool_call_id"):
            value = "<tool_response>\n" + json.dumps({
                "tool_call_id": _bounded_text(message.get("tool_call_id"), 160),
                "content": value,
            }, ensure_ascii=False) + "\n</tool_response>"
        conversations.append({"from": sender, "value": value})
    return _redact({
        "conversations": conversations,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": _bounded_text(model, 160),
        "completed": bool(completed),
    })


def build_run_evidence(payload: Dict[str, Any], *, session_id: str = "",
                       requested_provider: str = "", requested_profile: str = "",
                       requested_model: str = "", events: Any = None) -> Dict[str, Any]:
    """Build a bounded evidence record without persisting the full transcript."""
    attempts = payload.get("provider_attempts") if isinstance(payload, dict) else []
    attempts = attempts if isinstance(attempts, list) else []
    actions = payload.get("actions") if isinstance(payload, dict) else []
    actions = actions if isinstance(actions, list) else []
    provider = _successful_provider(attempts) or requested_provider or "unknown"
    model = requested_model or next(
        (str(item.get("model") or "") for item in attempts if isinstance(item, dict) and item.get("model")),
        "unknown",
    )
    evidence = {
        "schema_version": 1,
        "created_at": time.time(),
        "session_id": str(session_id or "")[:120],
        "turn_id": str(payload.get("turn_id") or "")[:120],
        "requested": {
            "provider": str(requested_provider or "")[:80],
            "profile": str(requested_profile or "")[:80],
            "model": str(requested_model or "")[:160],
        },
        "selected": {"provider": provider[:80], "model": model[:160]},
        "provider_attempts": attempts[-128:],
        "budget": payload.get("budget_report", {}),
        "verification": _verification_summary(payload.get("verification", {})),
        "trace": _trace_summary(payload, events=events, session_id=session_id),
        "trajectory": _trajectory_summary(payload, model, bool(payload.get("success"))),
        "tools": [
            {
                "name": str(item.get("name") or item.get("tool") or "tool")[:120],
                "success": bool(item.get("success")),
                "verified": bool(item.get("verified", item.get("success", False))),
            }
            for item in actions[-128:]
            if isinstance(item, dict)
        ],
        "outcome": {
            "success": bool(payload.get("success")),
            "error": str(payload.get("error") or "")[:500],
            "calls_executed": int(payload.get("calls_executed", 0) or 0),
        },
    }
    return _redact(evidence)


def write_run_evidence(root_dir: str, evidence: Dict[str, Any]) -> str:
    """Atomically persist one evidence bundle and return its absolute path."""
    root = Path(root_dir).resolve()
    _refresh_trace_artifact_status(evidence, str(root))
    _refresh_durable_verification(evidence, str(root))
    selected = evidence.get("selected") if isinstance(evidence, dict) else {}
    provider = _slug(selected.get("provider") if isinstance(selected, dict) else "")
    model = _slug(selected.get("model") if isinstance(selected, dict) else "")
    turn_id = _slug(evidence.get("turn_id"), fallback=f"run-{int(time.time() * 1000)}")
    directory = root / "workspace" / "provider_run_evidence" / provider / model
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{turn_id}.json"
    temporary = destination.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(_redact(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return str(destination)


__all__ = ["build_hermes_trajectory", "build_run_evidence", "write_run_evidence"]
