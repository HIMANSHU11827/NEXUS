"""NexusResearcher — STUB.

No autonomous research is implemented. Methods report their stub status
explicitly rather than returning fake success, so callers never mistake this
for a working research agent.
"""
from __future__ import annotations

__version__ = "0.1.0-stub"

from typing import Any, Dict

IS_STUB = True


def _stub(operation: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "stub",
        "confidence": None,
        "operation": operation,
        "reason": "NexusResearcher is not implemented (constructor-only stub).",
    }
    payload.update(extra)
    return payload


class NexusResearcher:
    """Constructor-only stub for the planned autonomous research agent."""

    is_stub = True

    def __init__(self, root: str):
        self.root = root

    def research(self, topic: str, **kwargs: Any) -> Dict[str, Any]:
        return _stub("research", topic=topic, findings=[])

    def investigate(self, question: str, **kwargs: Any) -> Dict[str, Any]:
        return _stub("investigate", question=question, findings=[])

    def status(self) -> Dict[str, Any]:
        return _stub("status")
