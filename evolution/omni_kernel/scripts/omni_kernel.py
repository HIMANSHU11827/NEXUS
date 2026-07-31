"""OmniEvolutionKernel — STUB.

The unified evolution orchestration layer is not implemented. Methods report
status="stub" / confidence=None instead of fake success so that callers (and
the kernel's lazy subsystem loader) cannot mistake it for a working kernel.
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
        "reason": "OmniEvolutionKernel is not implemented (constructor-only stub).",
    }
    payload.update(extra)
    return payload


class OmniEvolutionKernel:
    """Constructor-only stub for the planned omni evolution kernel."""

    is_stub = True

    def __init__(self, root: str):
        self.root = root

    def evolve(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return _stub("evolve")

    def run_cycle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return _stub("run_cycle")

    def status(self) -> Dict[str, Any]:
        return _stub("status")
