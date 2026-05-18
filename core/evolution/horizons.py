import os
import json
import time
from typing import List, Dict, Any

class StrategicHorizons:
    """
    NEXUS STRATEGIC HORIZONS v1.0
    Tracks long-term objectives that span across multiple sessions.
    The agent uses this to maintain multi-day goals.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.db_path = os.path.join(self.root, "workspace", "horizons.json")
        self.horizons = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.horizons, f, indent=2)

    def set_horizon(self, title: str, objective: str, kpis: List[str]):
        """Creates a long-term goal."""
        horizon = {
            "id": f"H-{int(time.time())}",
            "title": title,
            "objective": objective,
            "kpis": kpis,
            "progress": 0,
            "tasks_completed": [],
            "status": "ACTIVE",
            "created_at": time.time()
        }
        self.horizons.append(horizon)
        self._save()
        return horizon["id"]

    def update_progress(self, horizon_id: str, new_task: str, progress_incr: int):
        """Updates progress on a long-term goal."""
        for h in self.horizons:
            if h["id"] == horizon_id:
                h["tasks_completed"].append(new_task)
                h["progress"] = min(100, h["progress"] + progress_incr)
                if h["progress"] >= 100: h["status"] = "ARCHIVED"
                self._save()
                return True
        return False

    def get_active_horizons(self) -> str:
        active = [h for h in self.horizons if h["status"] == "ACTIVE"]
        if not active: return "No long-term strategic goals active."
        
        lines = ["# STRATEGIC_HORIZONS:"]
        for h in active:
            lines.append(f"- [{h['id']}] {h['title']}: {h['progress']}% Complete. Objective: {h['objective']}")
        return "\n".join(lines)
