"""
NEXUS ENSEMBLE — HyperAgents Ensemble system adapted for NEXUS.
Manages multiple agent solutions and selects the best one.
"""

import json
import os
import time
from typing import List, Dict, Any, Optional


class EnsembleManager:
    """
    Manages an archive of agent solutions and selects the best performers.
    Adapted from HyperAgents ensemble.py.
    """

    def __init__(self, workspace: str = "./workspace"):
        self.workspace = os.path.abspath(workspace)
        self.archive_path = os.path.join(self.workspace, "ensemble_archive.json")
        self.archive: List[Dict[str, Any]] = self._load_archive()

    def _load_archive(self) -> list:
        if os.path.exists(self.archive_path):
            try:
                with open(self.archive_path, "r") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return []

    def _save_archive(self):
        with open(self.archive_path, "w") as f:
            json.dump(self.archive, f, indent=2)

    def add_solution(
        self,
        agent_id: str,
        task: str,
        solution: str,
        score: float = 0.0,
        metadata: Dict[str, Any] = None,
    ):
        """Add a solution to the archive."""
        entry = {
            "agent_id": agent_id,
            "task": task,
            "solution": solution,
            "score": score,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self.archive.append(entry)
        self._save_archive()

    def get_best(self, task_filter: str = None) -> Optional[Dict[str, Any]]:
        """Get the best solution, optionally filtered by task."""
        candidates = self.archive
        if task_filter:
            candidates = [
                e
                for e in candidates
                if task_filter.lower() in e.get("task", "").lower()
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda x: x.get("score", 0))

    def get_top_n(self, n: int = 5, task_filter: str = None) -> List[Dict[str, Any]]:
        """Get top N solutions by score."""
        candidates = self.archive
        if task_filter:
            candidates = [
                e
                for e in candidates
                if task_filter.lower() in e.get("task", "").lower()
            ]
        return sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[:n]

    def evolve(
        self, task: str, parent_solution: str
    ) -> str:
        """
        Evolve a solution by prompting the LLM to improve it.
        """
        from providers.router import ModelRouter

        router = ModelRouter()
        prompt = f"""Given this task: {task}

Previous solution:
```
{parent_solution}
```

Improve this solution. Make it more robust, efficient, or correct.
Respond with just the improved solution."""

        try:
            return router.generate(prompt=prompt)
        except Exception as e:
            return f"Evolution error: {e}"

    def get_stats(self) -> Dict[str, Any]:
        if not self.archive:
            return {"total": 0}
        scores = [e.get("score", 0) for e in self.archive]
        return {
            "total": len(self.archive),
            "avg_score": sum(scores) / len(scores),
            "max_score": max(scores),
            "min_score": min(scores),
        }
