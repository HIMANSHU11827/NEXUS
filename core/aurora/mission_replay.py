"""Mission replay event log for auditable autonomous execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import time
from typing import Any, Dict, List


@dataclass
class ReplayEvent:
    event_type: str
    data: Dict[str, Any]
    mission_id: str = "default"
    timestamp: float = field(default_factory=time.time)


class MissionReplay:
    """Append-only black-box recorder for NEXUS actions."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "mission_replay.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, event_type: str, data: Dict[str, Any], mission_id: str = "default") -> ReplayEvent:
        event = ReplayEvent(event_type=event_type, data=self._safe_data(data), mission_id=mission_id)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def recent(self, limit: int = 50, mission_id: str = "") -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        events: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f.readlines()[-max(limit * 3, limit):]:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not mission_id or event.get("mission_id") == mission_id:
                    events.append(event)
        return events[-limit:]

    @staticmethod
    def _safe_data(data: Dict[str, Any]) -> Dict[str, Any]:
        def scrub(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: ("[REDACTED]" if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower() else scrub(v)) for k, v in value.items()}
            if isinstance(value, list):
                return [scrub(v) for v in value[:100]]
            text = str(value)
            return text[:4000] if len(text) > 4000 else value

        return scrub(data)
