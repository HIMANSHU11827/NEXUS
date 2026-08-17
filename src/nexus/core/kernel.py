"""NexusKernel - authoritative system root.

The kernel is the single owner of global state. It holds the control plane,
system state machine, and the canonical startup/shutdown sequences. It is
deliberately small: it coordinates, it does not implement subsystem business
logic. Subsystems plug in by registering services on the control plane.

It is designed to coexist with the pre-existing ``kernel/`` lazy subsystem
singleton and with ``nexus/__init__.py`` boot loader; it does not shadow them.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from nexus.core.control_plane import ControlPlane
from nexus.core.errors import StartupError
from nexus.core.shutdown_sequence import ShutdownSequence
from nexus.core.startup_sequence import StartupSequence
from nexus.core.system_state import SystemContext, SystemState
from nexus.core.state_machine import StateMachine


class NexusKernel:
    def __init__(self, context: Optional[SystemContext] = None) -> None:
        self.context = context or SystemContext()
        self.control = ControlPlane()
        self.startup = StartupSequence()
        self.shutdown = ShutdownSequence()
        self._fsm = StateMachine(SystemState.CREATED.value)
        self._fsm.add_transitions([
            (SystemState.CREATED.value, SystemState.BOOTSTRAPPING.value),
            (SystemState.BOOTSTRAPPING.value, SystemState.INITIALIZING.value),
            (SystemState.INITIALIZING.value, SystemState.VALIDATING.value),
            (SystemState.VALIDATING.value, SystemState.STARTING.value),
            (SystemState.STARTING.value, SystemState.RUNNING.value),
            (SystemState.RUNNING.value, SystemState.HEALTHY.value),
            (SystemState.RUNNING.value, SystemState.DEGRADED.value),
            (SystemState.HEALTHY.value, SystemState.DEGRADED.value),
            (SystemState.DEGRADED.value, SystemState.HEALTHY.value),
            (SystemState.RUNNING.value, SystemState.PAUSING.value),
            (SystemState.PAUSING.value, SystemState.PAUSED.value),
            (SystemState.PAUSED.value, SystemState.RESUMING.value),
            (SystemState.RESUMING.value, SystemState.RUNNING.value),
            (SystemState.RUNNING.value, SystemState.STOPPING.value),
            (SystemState.DEGRADED.value, SystemState.STOPPING.value),
            (SystemState.STOPPING.value, SystemState.STOPPED.value),
            (SystemState.RUNNING.value, SystemState.DIAGNOSING.value),
            (SystemState.DIAGNOSING.value, SystemState.REPAIRING.value),
            (SystemState.REPAIRING.value, SystemState.RECOVERING.value),
            (SystemState.RECOVERING.value, SystemState.RUNNING.value),
            (SystemState.RECOVERING.value, SystemState.RECOVERY_EXHAUSTED.value),
            (SystemState.RECOVERY_EXHAUSTED.value, SystemState.ESCALATED.value),
            (SystemState.ESCALATED.value, SystemState.STOPPING.value),
        ])
        self._booted = False

    @property
    def state(self) -> SystemState:
        return SystemState(self._fsm.state)

    def transition(self, target: SystemState) -> None:
        self._fsm.transition(target.value)

    def _advance(self, *targets: SystemState) -> None:
        for target in targets:
            if self.state != target:
                self.transition(target)

    async def boot(self) -> None:
        if self._booted:
            return
        self._advance(
            SystemState.BOOTSTRAPPING,
            SystemState.INITIALIZING,
            SystemState.VALIDATING,
        )
        try:
            await self.startup.run()
        except Exception as exc:  # noqa: BLE001
            raise StartupError(f"Startup failed: {exc}") from exc
        self._advance(SystemState.STARTING, SystemState.RUNNING)
        self._booted = True

    async def shutdown_now(self) -> None:
        self.transition(SystemState.STOPPING)
        await self.shutdown.run()
        self.transition(SystemState.STOPPED)
        self._booted = False

    def health(self) -> str:
        return self.control.overall_health().value
