"""Tool reputation and economy metrics for routing decisions."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List


class ToolEconomy:
    """Persistent per-tool success, latency, and risk metadata."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "tool_economy.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, tool_name: str, success: bool, duration_ms: float, read_only: bool = False, error: str = "") -> Dict[str, Any]:
        data = self._load()
        item = data.setdefault(
            tool_name,
            {
                "tool": tool_name,
                "calls": 0,
                "successes": 0,
                "failures": 0,
                "avg_latency_ms": 0.0,
                "success_rate": 0.0,
                "risk_hint": "read" if read_only else "write",
                "last_error": "",
                "last_used": 0.0,
            },
        )
        item["calls"] += 1
        item["successes"] += 1 if success else 0
        item["failures"] += 0 if success else 1
        calls = max(item["calls"], 1)
        item["avg_latency_ms"] = round(((item["avg_latency_ms"] * (calls - 1)) + duration_ms) / calls, 2)
        item["success_rate"] = round(item["successes"] / calls, 4)
        item["risk_hint"] = "read" if read_only else item.get("risk_hint", "write")
        item["last_error"] = "" if success else str(error)[:500]
        item["last_used"] = time.time()
        self._save(data)
        return item

    def rank(self) -> List[Dict[str, Any]]:
        data = self._load()
        tools = list(data.values())
        tools.sort(key=lambda t: (-float(t.get("success_rate", 0)), float(t.get("avg_latency_ms", 999999)), t.get("tool", "")))
        return tools

    def get(self, tool_name: str) -> Dict[str, Any]:
        return self._load().get(tool_name, {})

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: Dict[str, Dict[str, Any]]) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp, self.path)
