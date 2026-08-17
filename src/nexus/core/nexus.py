"""Nexus - the top-level system object.

Thin facade over :class:`NexusKernel`. Applications (CLI, API, gateway, main
agent) obtain a ``Nexus`` instance, register their subsystems as services on
``nexus.kernel.control``, build the startup/shutdown steps, and call
``nexus.run()`` / ``nexus.stop()``. Keeping this object small preserves the
"Nexus Core is not one giant class" rule.
"""

from __future__ import annotations

from typing import Optional

from nexus.core.kernel import NexusKernel
from nexus.core.system_state import SystemContext, SystemState


class Nexus:
    def __init__(self, context: Optional[SystemContext] = None,
                 kernel: Optional[NexusKernel] = None) -> None:
        self.kernel = kernel or NexusKernel(context)
        self.context = self.kernel.context

    @property
    def state(self) -> SystemState:
        return self.kernel.state

    @property
    def control(self):
        return self.kernel.control

    async def run(self) -> None:
        await self.kernel.boot()

    async def stop(self) -> None:
        await self.kernel.shutdown_now()

    @property
    def healthy(self) -> bool:
        return self.kernel.health() in ("healthy", "degraded")
