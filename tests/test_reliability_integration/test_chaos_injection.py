"""Chaos / failure-injection tests (mission §31).

Deterministic injections - no real network, no real providers. Each test
injects a failure class through the RecoveryEngine and asserts the runtime
reaches a precise, auditable outcome: recovered-via-failover, blocked with a
resumable state, quarantined component, or restarted-to-resumed.
"""

import asyncio
import json
import os

import pytest

from reliability.failure import FailureClass, envelope_from_exception
from reliability.goal import GoalState, GoalStore
from reliability.recovery import (
    RecoveryEngine,
    RecoveryResult,
    RecoveryVerdict,
)
from reliability.states import RunState, RunStateMachine


def env_for(cls, message, component_id="web_search", **kwargs):
    return envelope_from_exception(
        RuntimeError(message),
        component_type=kwargs.pop("component_type", "tool"),
        component_id=component_id,
        operation=kwargs.pop("operation", "execute"),
        failure_class=cls,
        **kwargs,
    )


class TestChaosInjections:
    @pytest.mark.asyncio
    async def test_provider_outage_fails_over_to_backup_provider(self):
        engine = RecoveryEngine(persist_dir=None)
        failed_over = []

        def failover_adapter(envelope, context):
            if envelope.failure_class == FailureClass.PROVIDER_OUTAGE:
                failed_over.append(envelope.provider or "unknown")
                return RecoveryResult(
                    verdict=RecoveryVerdict.RECOVERED,
                    strategy="switch_provider",
                    detail="switched to fallback provider",
                    recovered_component=envelope.component_id,
                )
            return None

        engine.register_adapter(failover_adapter)
        result = await engine.recover(
            env_for(
                FailureClass.PROVIDER_OUTAGE,
                "upstream 503",
                component_id="openai",
                component_type="provider",
                provider="openai",
                operation="chat",
            )
        )
        assert result.verdict == RecoveryVerdict.RECOVERED
        assert result.strategy == "switch_provider"
        assert failed_over == ["openai"]

    @pytest.mark.asyncio
    async def test_network_partition_blocks_with_resume_path(self):
        engine = RecoveryEngine(persist_dir=None, max_attempts=2)
        for _ in range(2):
            await engine.recover(
                env_for(FailureClass.NETWORK, "connection reset", component_id="web_search")
            )
        final = await engine.recover(
            env_for(FailureClass.NETWORK, "connection reset", component_id="web_search")
        )
        assert final.verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        assert final.strategy == "bounded_retries_exhausted"
        assert "switch provider" in final.next_action

    @pytest.mark.asyncio
    async def test_mcp_disconnect_quarantines_then_reconnects(self):
        engine = RecoveryEngine(persist_dir=None)

        def mcp_adapter(envelope, context):
            if envelope.failure_class == FailureClass.MCP_TRANSPORT:
                return RecoveryResult(
                    verdict=RecoveryVerdict.RECOVERED,
                    strategy="reconnect_mcp_server",
                    detail="reconnected and refreshed tool list",
                    recovered_component=envelope.component_id,
                )
            return None

        engine.register_adapter(mcp_adapter)
        for _ in range(2):
            result = await engine.recover(
                env_for(
                    FailureClass.MCP_TRANSPORT,
                    "stdio transport closed",
                    component_id="mcp.filesystem",
                    component_type="mcp",
                )
            )
        assert result.verdict == RecoveryVerdict.RECOVERED
        assert result.strategy == "reconnect_mcp_server"
        assert engine.is_quarantined("mcp", "mcp.filesystem") is False

    @pytest.mark.asyncio
    async def test_worker_crash_is_quarantined_and_task_reclaimable(self):
        engine = RecoveryEngine(persist_dir=None)

        def worker_adapter(envelope, context):
            if envelope.failure_class == FailureClass.WORKER_CRASH:
                return RecoveryResult(
                    verdict=RecoveryVerdict.RECOVERED,
                    strategy="reclaim_and_restart_worker",
                    detail="reclaimed leased tasks; restarted worker",
                    recovered_component=envelope.component_id,
                )
            return None

        engine.register_adapter(worker_adapter)
        result = await engine.recover(
            env_for(
                FailureClass.WORKER_CRASH,
                "worker died",
                component_id="worker-3",
                component_type="queue",
            )
        )
        assert result.verdict == RecoveryVerdict.RECOVERED
        assert result.strategy == "reclaim_and_restart_worker"
        assert engine.quarantined_components() == []

    @pytest.mark.asyncio
    async def test_repeated_identical_failures_escalate_to_blocked(self):
        engine = RecoveryEngine(persist_dir=None, max_attempts=3)
        outcomes = []
        for _ in range(3):
            outcomes.append(
                await engine.recover(
                    env_for(FailureClass.TOOL_EXECUTION, "boom", component_id="web_search")
                )
            )
        assert outcomes[0].verdict == RecoveryVerdict.RECOVERED
        assert outcomes[1].verdict == RecoveryVerdict.RECOVERED
        assert outcomes[2].verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        history = engine.strategy_history("tool|web_search|execute|tool_execution|tool_execution")
        assert history["attempts"] == 3
        assert history["frozen"] == ["bounded_retries_exhausted"]

    @pytest.mark.asyncio
    async def test_unrecoverable_failure_persists_resumable_state(self):
        engine = RecoveryEngine(persist_dir=None)
        machine = RunStateMachine(RunState.EXECUTING)
        result = await engine.recover(
            env_for(
                FailureClass.NON_RECOVERABLE_EXTERNAL,
                "external account suspended",
                component_id="billing",
            ),
            state_machine=machine,
        )
        assert result.verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        assert result.strategy == "non_recoverable_failure"
        assert machine.state == RunState.RECOVERING


class TestRestartResumption:
    def test_state_machine_resumes_after_restart(self, tmp_path):
        path = str(tmp_path / "machine.json")
        machine = RunStateMachine(RunState.INITIALIZING, persist_path=path)
        machine.transition(RunState.PLANNING, reason="turn 1")
        machine.transition(RunState.EXECUTING, reason="acting")
        machine.transition(RunState.PARTIALLY_COMPLETED, reason="step 3 of 5 done")
        del machine

        resumed = RunStateMachine(RunState.INITIALIZING, persist_path=path)
        assert resumed.state == RunState.PARTIALLY_COMPLETED
        reasons = [record.reason for record in resumed.history()]
        assert "step 3 of 5 done" in reasons

    def test_goal_survives_restart_with_recovery_history(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = GoalState.create("fix the build", goal_id="goal_g1")
        goal.blockers.append("needs credentials")
        store.save(goal)
        del goal

        reloaded = store.load("goal_g1")
        assert reloaded.parsed_objective == "fix the build"
        assert reloaded.blockers[0]["reason"] == "needs credentials"
        assert reloaded.is_terminal() is False

    def test_strategy_history_survives_restart(self, tmp_path):
        persist_dir = str(tmp_path / "recovery")
        engine = RecoveryEngine(persist_dir=persist_dir, max_attempts=3)
        asyncio.run(
            engine.recover(env_for(FailureClass.TOOL_EXECUTION, "boom", component_id="web_search"))
        )
        reloaded = RecoveryEngine(persist_dir=persist_dir, max_attempts=3)
        signature = "tool|web_search|execute|tool_execution|tool_execution"
        assert reloaded.strategy_history(signature)["attempts"] == 1
        result = asyncio.run(
            reloaded.recover(
                env_for(FailureClass.TOOL_EXECUTION, "boom", component_id="web_search")
            )
        )
        assert result.attempts == 2

    def test_quarantine_survives_restart(self, tmp_path):
        persist_dir = str(tmp_path / "recovery")
        engine = RecoveryEngine(persist_dir=persist_dir)
        engine.quarantine("mcp", "mcp.slow", "three timeouts")
        reloaded = RecoveryEngine(persist_dir=persist_dir)
        assert reloaded.is_quarantined("mcp", "mcp.slow")
        reloaded.unquarantine("mcp", "mcp.slow")
        assert reloaded.is_quarantined("mcp", "mcp.slow") is False