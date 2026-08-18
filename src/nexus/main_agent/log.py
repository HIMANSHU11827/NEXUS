"""V5Logger — structured loop logging for the V5 loop.

Own logging surface for the V5 loop: stage transitions, tool lifecycle,
runtime events, and a JSONL audit trail (``.nexus/v5/v5_log.jsonl``).

This module is part of the V5 loop architecture — it is a V5 module, not a
V1 module and not a port of V1. It is dependency-free: no imports from
``core``, every method is defensive and never raises, so logging can never
break the loop.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class V5Logger:
    """Mixin giving the V5 loop a structured logging surface.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.root_dir`` - project root used to resolve the audit log path
      (``.nexus/v5/v5_log.jsonl``).
    - ``self.session_id`` - session id stamped on every audit entry.
    - ``self.logger`` - python logger exposing ``.info``/``.warning``.
    """

    def _log_path(self) -> str:
        """Resolve the JSONL audit log path; "" on failure."""
        try:
            root = getattr(self, "root_dir", None) or os.getcwd()
            return os.path.join(root, ".nexus", "v5", "v5_log.jsonl")
        except Exception:
            return ""

    def _log_stage(
        self, stage: str, *, extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a loop stage transition to the logger and the audit trail."""
        try:
            self.logger.info("[V5LOOP] stage=%s", stage)
            entry: Dict[str, Any] = {
                "ts": time.time(),
                "kind": "stage",
                "stage": stage,
            }
            if extra:
                entry["extra"] = extra
            self._log_append(entry)
        except Exception:
            pass

    def _log_tool(
        self,
        tool_name: str,
        status: str,
        duration_ms: float = 0.0,
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log one tool execution outcome to the audit trail."""
        try:
            entry: Dict[str, Any] = {
                "ts": time.time(),
                "kind": "tool",
                "tool": tool_name,
                "status": status,
                "duration_ms": round(duration_ms, 3),
            }
            if extra:
                entry["extra"] = extra
            self._log_append(entry)
        except Exception:
            pass

    def _log_runtime(
        self,
        event_type: str,
        status: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a runtime event to the audit trail."""
        try:
            entry: Dict[str, Any] = {
                "ts": time.time(),
                "kind": "runtime",
                "event": event_type,
                "status": status,
            }
            if payload:
                entry["payload"] = payload
            self._log_append(entry)
        except Exception:
            pass

    def _log_append(self, entry: Dict[str, Any]) -> bool:
        """Append one JSON line to the audit trail; False on failure."""
        try:
            path = self._log_path()
            if not path:
                return False
            entry.setdefault("session", getattr(self, "session_id", "default"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False

    def _log_lines(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Read the most recent audit lines; [] on failure."""
        try:
            path = self._log_path()
            if not path or not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            parsed: List[Dict[str, Any]] = []
            for line in lines[-limit:]:
                try:
                    parsed.append(json.loads(line))
                except Exception:
                    continue
            return parsed
        except Exception:
            return []

    def _log_stats(self) -> Dict[str, Any]:
        """Summary of the audit trail state."""
        try:
            path = self._log_path()
            if not path or not os.path.exists(path):
                return {"path": path, "entries": 0}
            with open(path, "r", encoding="utf-8") as fh:
                count = sum(1 for _ in fh)
            return {"path": path, "entries": count}
        except Exception:
            return {"path": "", "entries": 0}
