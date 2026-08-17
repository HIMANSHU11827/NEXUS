"""Declarative shutdown sequence.

Mirrors the target shutdown contract: stop accepting unsafe new work, let safe
active work finish, save goals/plans/tasks, flush memory/queues, disconnect
gateways, stop subsystems in reverse order, release resources. Every step is
best-effort and idempotent; a failure in one step does not block the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, List


class ShutdownStepStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ShutdownStep:
    order: int
    name: str
    action: Callable[[], Awaitable[None]]
    status: ShutdownStepStatus = ShutdownStepStatus.SKIPPED


class ShutdownSequence:
    def __init__(self) -> None:
        self.steps: List[ShutdownStep] = []

    def add(self, order: int, name: str, action: Callable[[], Awaitable[None]]) -> None:
        self.steps.append(ShutdownStep(order=order, name=name, action=action))

    async def run(self) -> dict:
        results = {}
        for step in sorted(self.steps, key=lambda s: s.order):
            try:
                await step.action()
                step.status = ShutdownStepStatus.OK
                results[step.name] = "ok"
            except Exception:  # noqa: BLE001 - best-effort shutdown
                step.status = ShutdownStepStatus.FAILED
                results[step.name] = "failed"
        return results

    def summary(self) -> str:
        return "\n".join(f"[{s.status.value:>7}] {s.order:>2}. {s.name}"
                         for s in sorted(self.steps, key=lambda s: s.order))
