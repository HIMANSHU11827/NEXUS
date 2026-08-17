"""Declarative startup sequence.

Models the 39-step startup defined by the target architecture as an ordered,
classifiable list. Each step is either FATAL (must succeed), DEGRADABLE
(continue in degraded mode if it fails), or OPTIONAL (ignore failure). The
orchestrator runs them in order, recording status, and refuses to mark Nexus
healthy if a FATAL step failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, List, Optional


class StepClass(str, Enum):
    FATAL = "fatal"
    DEGRADABLE = "degradable"
    OPTIONAL = "optional"


@dataclass
class StartupStep:
    order: int
    name: str
    action: Callable[[], Awaitable[None]]
    cls: StepClass = StepClass.FATAL
    result: Optional[str] = None
    error: Optional[str] = None


class StartupSequence:
    def __init__(self) -> None:
        self.steps: List[StartupStep] = []

    def add(self, order: int, name: str, action: Callable[[], Awaitable[None]],
            cls: StepClass = StepClass.FATAL) -> None:
        self.steps.append(StartupStep(order=order, name=name, action=action, cls=cls))

    async def run(self) -> dict:
        results = {}
        for step in sorted(self.steps, key=lambda s: s.order):
            try:
                await step.action()
                step.result = "ok"
            except Exception as exc:  # noqa: BLE001
                step.error = str(exc)
                step.result = "failed"
                if step.cls == StepClass.FATAL:
                    raise
            results[step.name] = step.result
        return results

    def summary(self) -> str:
        return "\n".join(f"[{s.result or 'skip':>4}] {s.order:>2}. {s.name}"
                         for s in sorted(self.steps, key=lambda s: s.order))
