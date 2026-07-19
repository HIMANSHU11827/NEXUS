from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class ToolEconomy:
    """Ranks recent tool/activity usage from persisted work events."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.events_dir = os.path.join(root, "workspace", "work_events")

    def rank(self) -> List[Dict[str, Any]]:
        counts: Dict[str, Dict[str, Any]] = {}
        if not os.path.isdir(self.events_dir):
            return []
        for name in os.listdir(self.events_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.events_dir, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        key = str(event.get("tool") or event.get("kind") or event.get("type") or "tool")
                        row = counts.setdefault(key, {"tool": key, "count": 0, "success": 0, "errors": 0})
                        row["count"] += 1
                        status = str(event.get("status") or "").lower()
                        if status in {"done", "success"}:
                            row["success"] += 1
                        if status in {"error", "failed"}:
                            row["errors"] += 1
            except OSError:
                continue
        rows = list(counts.values())
        rows.sort(key=lambda row: (-int(row["count"]), str(row["tool"])))
        return rows
