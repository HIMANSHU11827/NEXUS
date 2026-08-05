"""Ensemble Manager — ranks multiple candidate answers and picks the strongest.

Scoring is intentionally simple and transparent: confidence (0-40), evidence
presence (0-20), verification (0-20), answer length/substance (0-20). It never
fabricates strategies or confidence — if zero or one candidate is available it
says so instead of pretending to run an ensemble.
"""

from __future__ import annotations

__version__ = "2.1.0"

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IS_STUB = False

_WEIGHT_CONFIDENCE = 40.0
_WEIGHT_EVIDENCE = 20.0
_WEIGHT_VERIFIED = 20.0
_WEIGHT_LENGTH = 20.0


@dataclass
class EnsembleResult:
    strategy: str
    output: str
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnsembleManager:
    """Ranks candidate results and returns {winner, score, runner_up, ensemble_size}."""

    is_stub = False

    def __init__(self, workspace: str) -> None:
        self.workspace = workspace
        self.strategies: List[str] = ["direct", "cot", "decompose", "verify"]
        self._results: List[EnsembleResult] = []
        self._last_selection: Dict[str, Any] = {}

    # ── Core: pick a winner ────────────────────────────────────────────

    def select_winner(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Score candidate results and return winner/runner_up/ensemble_size.

        Each candidate is a dict with at least ``answer``; optional fields
        ``confidence`` (0..1), ``evidence`` (list/str), and ``verified``
        (bool) raise its score. Empty input is an honest no-op.
        """
        if not candidates:
            return {"winner": None, "score": 0, "runner_up": None, "ensemble_size": 0}

        scored = [(candidate, self._score_candidate(candidate)) for candidate in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        winner_raw, winner_score = scored[0]
        winner = {**winner_raw, "score": winner_score}
        runner_up = None
        if len(scored) > 1:
            runner_raw, runner_score = scored[1]
            runner_up = {**runner_raw, "score": runner_score}

        selection = {
            "winner": winner,
            "score": winner_score,
            "runner_up": runner_up,
            "ensemble_size": len(candidates),
        }
        self._last_selection = selection
        return selection

    def _score_candidate(self, candidate: Dict[str, Any]) -> float:
        score = 0.0

        confidence = candidate.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            score += max(0.0, min(1.0, float(confidence))) * _WEIGHT_CONFIDENCE

        answer = str(candidate.get("answer") or "")
        if answer.strip():
            score += min(len(answer.strip()) / 1000.0, 1.0) * _WEIGHT_LENGTH

        evidence = candidate.get("evidence")
        if isinstance(evidence, (list, tuple)):
            has_evidence = any(str(piece).strip() for piece in evidence)
        elif isinstance(evidence, str):
            has_evidence = bool(evidence.strip())
        else:
            has_evidence = False
        if has_evidence:
            score += _WEIGHT_EVIDENCE

        verified = candidate.get("verified", candidate.get("verified_by_check", False))
        if isinstance(verified, bool) and verified:
            score += _WEIGHT_VERIFIED

        return round(score, 2)

    # ── Existing API (kept honest) ─────────────────────────────────────

    def run_ensemble(self, problem: str, candidates: Optional[List[Dict[str, Any]]] = None) -> EnsembleResult:
        """Select among ``candidates`` for ``problem``; without candidates this
        reports an honest single-candidate no-op rather than a fake ensemble."""
        if candidates:
            selection = self.select_winner(candidates)
            winner = selection["winner"] or {}
            result = EnsembleResult(
                strategy="ensemble",
                output=str(winner.get("answer") or ""),
                confidence=round(selection["score"] / 100.0, 2) if selection["score"] > 0 else None,
                metadata={
                    "status": "ok",
                    "problem": problem,
                    "selection": selection,
                    "timestamp": time.time(),
                },
            )
        else:
            result = EnsembleResult(
                strategy="single",
                output=problem,
                confidence=None,
                metadata={
                    "status": "single_candidate",
                    "reason": "no candidate results provided; an ensemble needs "
                              "candidates=[{answer, confidence, evidence, ...}, ...]",
                    "problem": problem,
                    "ensemble_size": 0,
                    "timestamp": time.time(),
                },
            )
        self._results.append(result)
        return result

    def get_history(self) -> List[EnsembleResult]:
        return self._results.copy()
