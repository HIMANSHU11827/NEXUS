"""Lightweight per-skill experience tracking for NEXUS AI.

Pure standard library, never raises, no self-tuning. Tracks usage counters for
the ledger / tool-feedback plumbing:

    ~/.nexus/skills/experience.json -> {skill_id: {uses, successes, failures, last_used}}

The store is best-effort: any I/O or corruption error is swallowed so a broken
experience file can never prevent skills or the core loop from loading.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_EXPERIENCE_FILENAME = "experience.json"


class SkillExperience:
    """Thread-safe-ish, crash-safe per-skill experience store."""

    def __init__(self, path: Optional[str] = None) -> None:
        if path is not None:
            self._path = Path(path)
        else:
            self._path = Path.home() / ".nexus" / "skills" / DEFAULT_EXPERIENCE_FILENAME
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ─── persistence ─────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._path.is_file():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ─── API ─────────────────────────────────────────────────────

    def record(self, skill_id: str, success: bool = True, latency_ms: float = 0.0) -> bool:
        """Record one use of a skill. Returns False on any failure (never raises)."""
        try:
            skill_id = str(skill_id)
            if not skill_id:
                return False
            entry = self._data.setdefault(
                skill_id, {"uses": 0, "successes": 0, "failures": 0, "last_used": 0.0}
            )
            entry["uses"] = int(entry.get("uses", 0)) + 1
            if success:
                entry["successes"] = int(entry.get("successes", 0)) + 1
            else:
                entry["failures"] = int(entry.get("failures", 0)) + 1
            entry["last_used"] = time.time()
            self._save()
            return True
        except Exception:
            return False

    def get(self, skill_id: Optional[str] = None) -> Dict[str, Any]:
        """Experience for one skill, or a copy of the whole store."""
        if skill_id is None:
            return {k: dict(v) for k, v in self._data.items()}
        return dict(self._data.get(str(skill_id), {}))

    def get_experience(self, skill_id: Optional[str] = None) -> Dict[str, Any]:
        """Alias exposing the same shape the engine uses."""
        return self.get(skill_id)

    def summary(self) -> Dict[str, Any]:
        """Compact aggregate useful for health dashboards."""
        return {
            "path": str(self._path),
            "skills": len(self._data),
            "total_uses": sum(int(e.get("uses", 0)) for e in self._data.values()),
        }

    def clear(self) -> None:
        """Wipe the store (used by tests). Never raises."""
        try:
            self._data = {}
            if self._path.is_file():
                self._path.unlink()
        except Exception:
            pass

    @property
    def path(self) -> Path:
        return self._path

    # ─── dict compatibility ──────────────────────────────────────

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, skill_id: object) -> bool:
        return str(skill_id) in self._data
