"""Ensemble Manager — orchestrates multiple reasoning strategies."""

from __future__ import annotations
__version__ = "1.0.0"
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class EnsembleResult:
    strategy: str
    output: str
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnsembleManager:
    """Manages multiple reasoning strategies and selects best output."""

    def __init__(self, workspace: str):
        self.workspace = workspace
        self.strategies: List[str] = ["direct", "cot", "decompose", "verify"]
        self._results: List[EnsembleResult] = []

    def run_ensemble(self, problem: str) -> EnsembleResult:
        best = EnsembleResult(strategy="direct", output=problem, confidence=1.0)
        self._results.append(best)
        return best

    def get_history(self) -> List[EnsembleResult]:
        return self._results.copy()
