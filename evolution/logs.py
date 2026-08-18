"""Durable, small-footprint evolution outcome log used by the main loop.

The evolution package historically imported ``EvolutionLog`` from this module,
but the implementation was missing.  Keep the format intentionally simple:
append-only JSONL under ``.nexus/logs/evolution.jsonl`` so writes are inspectable,
recoverable, and safe to use from background finalization.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Iterable


class EvolutionLog:
    """Record wins, failures, and improvement actions for later analysis."""

    def __init__(self, root: str = ".") -> None:
        self.root = os.path.abspath(root)
        self.path = os.path.join(self.root, ".nexus", "logs", "evolution.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "event_id": entry.get("event_id") or f"evo_{uuid.uuid4().hex}",
            "timestamp": entry.get("timestamp") or time.time(),
            **entry,
        }
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def win(self, kind: str, name: str, message: str, score: float = 0.0, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._append({
            "outcome": "win", "kind": kind, "name": name,
            "message": message, "score": score, "metadata": metadata or {},
        })

    def lose(self, kind: str, name: str, message: str, score: float = 0.0, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._append({
            "outcome": "lose", "kind": kind, "name": name,
            "message": message, "score": score, "metadata": metadata or {},
        })

    def improvement(self, action: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._append({
            "outcome": "improvement", "action": action,
            "metadata": metadata or {},
        })

    def _records(self) -> Iterable[Dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(item, dict):
                            yield item
        except FileNotFoundError:
            return

    def stats(self) -> Dict[str, Any]:
        records = list(self._records())
        return {
            "total_events": len(records),
            "wins": sum(item.get("outcome") == "win" for item in records),
            "losses": sum(item.get("outcome") == "lose" for item in records),
            "improvements": sum(item.get("outcome") == "improvement" for item in records),
            "last_event_at": records[-1].get("timestamp") if records else None,
        }

