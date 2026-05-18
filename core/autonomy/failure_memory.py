"""Persistent failure memory for self-correction and regression prevention."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import time
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FailureRecord:
    task: str
    tool: str
    error: str
    context: Dict[str, Any]
    timestamp: float


class FailureMemory:
    """Append-only JSONL memory of concrete failures."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "failure_memory.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, task: str, tool: str, error: str, context: Optional[Dict[str, Any]] = None) -> None:
        record = FailureRecord(
            task=task[:500],
            tool=tool[:120],
            error=error[:1000],
            context=context or {},
            timestamp=time.time(),
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
