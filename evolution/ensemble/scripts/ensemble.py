"""Ensemble Manager — orchestrates multiple reasoning strategies."""

from __future__ import annotations

__version__ = "2.0.0"
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EnsembleResult:
    strategy: str
    output: str
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnsembleManager:
    """Manages multiple reasoning strategies and selects best output."""

    def __init__(self, workspace: str):
        self.workspace = workspace
        self.strategies: List[str] = ["direct", "cot", "decompose", "verify"]
        self._results: List[EnsembleResult] = []

    def run_ensemble(self, problem: str) -> EnsembleResult:
        """STUB — no real multi-strategy reasoning is implemented yet.

        Previously this returned confidence=1.0, which made callers treat a
        pass-through echo as a fully-confident ensemble result. It now reports
        its stub status honestly: status="stub" and confidence=None.
        """
        result = EnsembleResult(
            strategy="stub",
            output=problem,
            confidence=None,
            metadata={
                "status": "stub",
                "confidence": None,
                "reason": "EnsembleManager.run_ensemble is not implemented; "
                          "no strategies were executed.",
                "available_strategies": list(self.strategies),
            },
        )
        self._results.append(result)
        return result

    def get_history(self) -> List[EnsembleResult]:
        return self._results.copy()
