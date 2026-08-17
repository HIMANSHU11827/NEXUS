"""Tests for reliability.recovery: recovery engine, adapters, quarantine."""

import asyncio

import pytest

from reliability.failure import FailureClass, FailureEnvelope, envelope_from_exception
from reliability.goal import GoalState
from reliability.recovery import (
    RecoveryEngine,
    RecoveryResult,
    RecoveryVerdict,
    default_retry_policy,
)
from reliability.states import RunState, RunStateMachine


def tool_envelope(message="boom", cls=FailureClass.TOOL_EXECUTION, component_id="web_search"):
    return envelope_from_exception(
        RuntimeError(message),
        component_type="tool",
        component_id=component_id,
        operation="execute",
        failure_class=cls,
        tool=component_id,
    )


class TestRecoveryVerdicts:
    @pytest.mark.asyncio
    async def test_adapter_recovers(self):
        engine = RecoveryEngine(persist_dir=None)

        def adapter(envelope, context):
            if envelope.component_type == "tool":
                return RecoveryResult(
                    verdict=RecoveryVerdict.RECOVERED,
                    strategy="restart_tool",
                    detail="restarted",
                    recovered_component=envelope.component_id,
                )
            return None

        engine.register_adapter(adapter)
        result = await engine.recover(tool_envelope())
        assert result.verdict == RecoveryVerdict.RECOVERED
        assert result.strategy == "restart_tool"

    @pytest.mark.asyncio
    async def test_no_adapter_uses_generic_ladder(self):
        engine = RecoveryEngine(persist_dir=None)
        result = await engine.recover(tool_envelope())
        assert result.verdict in (RecoveryVerdict.RECOVERED, RecoveryVerdict.BLOCKED_NON_RECOVERABLE)
        assert result.strategy == "retry_with_backoff"

    @pytest.mark.asyncio
    async def test_transient_retry_result(self):
        engine = RecoveryEngine(persist_dir=None, max_attempts=3)
        env = envelope_from_exception(
            TimeoutError("slow"),
            component_type="provider",
            component_id="openai",
            operation="chat",
            failure_class=FailureClass.TIMEOUT,
        )
        result = await engine.recover(env)
        assert result.verdict == RecoveryVerdict.RECOVERED
        assert result.strategy == "retry_with_backoff"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_strategy_switches_after_repeat_failure(self):
        engine = RecoveryEngine(persist_dir=None, max_attempts=2)
        env = tool_envelope()
        first = await engine.recover(env)
        assert first.strategy == "retry_with_backoff"
        second = await engine.recover(env)
        assert second.strategy != first.strategy
        assert second.verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        assert second.attempts == 2
        assert "retry_with_backoff" in second.previous_strategies

    @pytest.mark.asyncio
    async def test_blocked_after_max_attempts(self):
        engine = RecoveryEngine(persist_dir=None, max_attempts=2)
        env = tool_envelope()
        for _ in range(2):
            await engine.recover(env)
        final = await engine.recover(env)
        assert final.verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        assert final.next_action  # precise next action required

    @pytest.mark.asyncio
    async def test_non_recoverable_blocks(self):
        engine = RecoveryEngine(persist_dir=None)
        env = envelope_from_exception(
            asyncio.CancelledError(),
            component_type="queue",
            component_id="w1",
            operation="run",
            failure_class=FailureClass.USER_CANCELLATION,
        )
        result = await engine.recover(env)
        assert result.verdict == RecoveryVerdict.BLOCKED_NON_RECOVERABLE
        assert result.strategy == "non_recoverable_failure"

    @pytest.mark.asyncio
    async def test_permission_waiting_for_user(self):
        engine = RecoveryEngine(persist_dir=None)
        env = envelope_from_exception(
            PermissionError("approval required"),
            component_type="tool",
            component_id="deleting",
            operation="delete",
            failure_class=FailureClass.PERMISSION_REQUIRED,
        )
        result = await engine.recover(env)
        assert result.verdict == RecoveryVerdict.WAITING_FOR_USER
        assert result.strategy == "request_user_action"

    @pytest.mark.asyncio
    async def test_goal_gets_recovery_history(self):
        engine = RecoveryEngine(persist_dir=None)
        goal = GoalState.create("do the thing")
        await engine.recover(tool_envelope(), goal=goal)
        assert len(goal.recovery_history) == 1
        assert goal.recovery_history[0]["strategy"]

    @pytest.mark.asyncio
    async def test_state_machine_enters_recovering(self):
        engine = RecoveryEngine(persist_dir=None)
        machine = RunStateMachine(RunState.EXECUTING)
        await engine.recover(tool_envelope(), state_machine=machine)
        assert machine.state == RunState.RECOVERING

    @pytest.mark.asyncio
    async def test_event_sink_receives_recovery_event(self):
        events = []
        engine = RecoveryEngine(persist_dir=None, event_sink=events.append)
        await engine.recover(tool_envelope())
        assert any(event["event_type"] == "reliability.recovery" for event in events)
        recovery_events = [
            event for event in events if event["event_type"] == "reliability.recovery"
        ]
        assert recovery_events[0]["verdict"] == "recovered"
        assert recovery_events[0]["component_id"] == "web_search"

    @pytest.mark.asyncio
    async def test_adapter_exception_does_not_abort(self):
        engine = RecoveryEngine(persist_dir=None)

        def bad_adapter(envelope, context):
            raise RuntimeError("adapter exploded")

        engine.register_adapter(bad_adapter)
        result = await engine.recover(tool_envelope())
        assert result.verdict == RecoveryVerdict.RECOVERED  # generic ladder

    @pytest.mark.asyncio
    async def test_blocked_adapter_does_not_block_later_adapter(self):
        engine = RecoveryEngine(persist_dir=None)

        def blocked_first(envelope, context):
            return RecoveryResult(
                verdict=RecoveryVerdict.BLOCKED_NON_RECOVERABLE,
                strategy="first",
                recovered_component=envelope.component_id,
            )

        def recovering_second(envelope, context):
            return RecoveryResult(
                verdict=RecoveryVerdict.RECOVERED,
                strategy="second",
                recovered_component=envelope.component_id,
            )

        engine.register_adapter(blocked_first)
        engine.register_adapter(recovering_second)
        result = await engine.recover(tool_envelope())
        assert result.strategy == "second"
        assert result.verdict == RecoveryVerdict.RECOVERED

    @pytest.mark.asyncio
    async def test_recovery_events_visible_on_blocked(self):
        events = []
        engine = RecoveryEngine(persist_dir=None, event_sink=events.append, max_attempts=1)
        env = tool_envelope()
        await engine.recover(env)
        await engine.recover(env)
        blocked = [
            event for event in events
            if event["event_type"] == "reliability.recovery"
            and event["verdict"] == "blocked_non_recoverable"
        ]
        assert blocked
        assert blocked[0]["next_action"]


class TestQuarantine:
    @pytest.mark.asyncio
    async def test_quarantine_and_restore(self):
        engine = RecoveryEngine(persist_dir=None)
        assert not engine.is_quarantined("tool", "web_search")
        engine.quarantine("tool", "web_search", "three timeouts")
        assert engine.is_quarantined("tool", "web_search")
        engine.unquarantine("tool", "web_search")
        assert not engine.is_quarantined("tool", "web_search")

    @pytest.mark.asyncio
    async def test_quarantine_event_emitted(self):
        events = []
        engine = RecoveryEngine(persist_dir=None, event_sink=events.append)
        engine.quarantine("mcp", "server-1", "disconnected")
        assert any(event["event_type"] == "reliability.quarantine" for event in events)


class TestPersistence:
    def test_strategy_history_persisted(self, tmp_path):
        engine = RecoveryEngine(persist_dir=str(tmp_path / "rec"))
        env = tool_envelope()
        asyncio.run(engine.recover(env))
        reloaded = RecoveryEngine(persist_dir=str(tmp_path / "rec"))
        assert reloaded.strategy_history(env.signature())["attempts"] >= 1

    def test_quarantine_persisted(self, tmp_path):
        engine = RecoveryEngine(persist_dir=str(tmp_path / "rec"))
        engine.quarantine("tool", "x", "r")
        reloaded = RecoveryEngine(persist_dir=str(tmp_path / "rec"))
        assert reloaded.is_quarantined("tool", "x")


class TestRetryPolicy:
    def test_delays_grow_and_are_positive(self):
        policy = default_retry_policy(max_attempts=5, base_delay=1.0, multiplier=2.0, jitter=0)
        assert policy(1) == 1.0
        assert policy(2) == 2.0
        assert policy(3) == 4.0
        assert policy(5) == 16.0

    def test_delay_capped(self):
        policy = default_retry_policy(base_delay=1.0, multiplier=2.0, max_delay=5.0, jitter=0)
        assert policy(10) == 5.0