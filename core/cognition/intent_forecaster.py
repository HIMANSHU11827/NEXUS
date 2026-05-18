"""Predict next likely user needs from project state and recent tasks."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Dict, List


@dataclass(frozen=True)
class Forecast:
    need: str
    confidence: float
    reason: str


class IntentForecaster:
    """Heuristic proactive assistant for missing likely next steps."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def forecast(self, recent_tasks: List[str], repo_signals: Dict[str, int] | None = None) -> List[Forecast]:
        repo_signals = repo_signals or {}
        text = " ".join(recent_tasks).lower()
        forecasts: List[Forecast] = []
        if any(k in text for k in ["fix", "bug", "refactor"]) and "test" not in text:
            forecasts.append(Forecast("run targeted regression tests", 0.82, "code changes usually need verification"))
        if any(k in text for k in ["dashboard", "api", "upload", "auth"]):
            forecasts.append(Forecast("run backend/dashboard security checks", 0.78, "API surface changed or was discussed"))
        if repo_signals.get("python_files", 0) > 20:
            forecasts.append(Forecast("refresh repo map and symbol graph", 0.7, "large Python project benefits from current structural map"))
        if "memory" in text or "rag" in text:
            forecasts.append(Forecast("run retrieval regression tests", 0.76, "memory changes are easy to silently degrade"))
        return forecasts
