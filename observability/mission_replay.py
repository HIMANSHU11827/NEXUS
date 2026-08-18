from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class MissionReplay:
    """Reads recent GUI work events for the audit timeline."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.events_dir = os.path.join(root, ".nexus", "workspace", "work_events")

    def recent(self, limit: int = 12) -> List[Dict[str, Any]]:
        if not os.path.isdir(self.events_dir):
            return []
        rows: List[Dict[str, Any]] = []
        for name in os.listdir(self.events_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.events_dir, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        rows.append({
                            "session_id": event.get("session_id") or name[:-6],
                            "turn_id": event.get("turn_id", ""),
                            "kind": event.get("kind") or event.get("type") or "tool",
                            "action": event.get("action") or event.get("title") or "Work event",
                            "target": event.get("target") or event.get("path") or event.get("command") or "",
                            "status": event.get("status", "running"),
                            "created_at": event.get("created_at", 0),
                        })
            except OSError:
                continue
        rows.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
        return rows[:limit]
