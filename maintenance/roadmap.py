from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List


class RoadmapAuditor:
    """Extracts checkbox-style roadmap status from repository docs."""

    ROADMAP_NAMES = {"roadmap.md", "todo.md", "task.md", "implementation_plan.md"}

    def __init__(self, root: str) -> None:
        self.root = root

    def _candidate_files(self) -> List[str]:
        candidates: List[str] = []
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "external"}]
            for name in files:
                lower = name.lower()
                if lower in self.ROADMAP_NAMES or "roadmap" in lower:
                    candidates.append(os.path.join(base, name))
        return candidates[:80]

    def audit(self) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        counts = {"done": 0, "pending": 0, "running": 0}
        pattern = re.compile(r"^\s*[-*]\s*\[([ xX/~-])\]\s*(.+)$")
        for path in self._candidate_files():
            rel = os.path.relpath(path, self.root)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        match = pattern.match(line)
                        if not match:
                            continue
                        mark = match.group(1).lower()
                        status = "done" if mark == "x" else "running" if mark in {"/", "~"} else "pending"
                        counts[status] += 1
                        items.append({
                            "item": match.group(2).strip(),
                            "status": status,
                            "phase": rel,
                            "source": f"{rel}:{line_no}",
                            "evidence": [f"{rel}:{line_no}"],
                            "remaining": [] if status == "done" else ["Complete and verify this roadmap item."],
                        })
            except OSError:
                continue
        total = len(items)
        completion_ratio = (counts["done"] / total) if total else 0
        return {
            "total": total,
            "counts": counts,
            "completion_ratio": completion_ratio,
            "remaining_top": [item["item"] for item in items if item["status"] != "done"][:10],
            "items": items,
        }

    def write_status(self) -> str:
        audit = self.audit()
        path = os.path.join(self.root, "workspace", "roadmap_status.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [
            "# Roadmap Status",
            "",
            f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total: {audit['total']}",
            f"Done: {audit['counts'].get('done', 0)}",
            f"Running: {audit['counts'].get('running', 0)}",
            f"Pending: {audit['counts'].get('pending', 0)}",
            "",
            "## Remaining top items",
        ]
        lines.extend(f"- {item}" for item in audit["remaining_top"])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).strip() + "\n")
        return path
