from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from nexus.run_control import RunControlRegistry
from nexus.main_agent.model import V5ModelCaller
from nexus.main_agent.tools import V5ToolExecutor


def test_cancel_before_registration_survives_generator_startup():
    registry = RunControlRegistry()
    assert registry.request_cancel("turn-1") is True
    control = registry.register("turn-1")
    assert control.cancelled is True
    assert control.reason == "user_cancelled"


def test_cancellation_is_scoped_to_one_turn():
    registry = RunControlRegistry()
    registry.register("turn-a")
    registry.register("turn-b")
    registry.request_cancel("turn-a", "operator")
    assert registry.get("turn-a").cancelled is True
    assert registry.get("turn-b").cancelled is False


def test_duplicate_cancel_is_idempotent_and_unregister_cleans_up():
    registry = RunControlRegistry()
    registry.register("turn-1")
    assert registry.request_cancel("turn-1") is True
    assert registry.request_cancel("turn-1", "second_request") is True
    assert registry.get("turn-1").reason == "second_request"
    registry.unregister("turn-1")
    assert registry.get("turn-1") is None


def test_deadline_is_monotonic_and_scoped():
    registry = RunControlRegistry()
    active = registry.register("active", deadline_at=time.monotonic() + 1.0)
    expired = registry.register("expired", deadline_at=time.monotonic() - 1.0)
    assert active.remaining is not None and active.remaining > 0
    assert active.timed_out is False
    assert expired.timed_out is True
    assert expired.remaining == 0.0


def test_register_does_not_extend_existing_deadline():
    registry = RunControlRegistry()
    first = registry.register("turn", deadline_at=time.monotonic() + 0.2)
    original = first.deadline_at
    second = registry.register("turn", deadline_at=time.monotonic() + 100.0)
    assert second is first
    assert second.deadline_at == original


def test_pending_cancel_and_deadline_are_isolated_by_turn_id():
    registry = RunControlRegistry()
    pending_deadline = time.monotonic() - 1.0
    assert registry.request_cancel("old-turn", "stale-request") is True

    fresh = registry.register("new-turn", deadline_at=time.monotonic() + 10.0)
    assert fresh.cancelled is False
    assert fresh.timed_out is False
    assert registry.get("old-turn").cancelled is True
    assert registry.get("old-turn").deadline_at is None

    expired = registry.register("expired-turn", deadline_at=pending_deadline)
    assert expired.timed_out is True
    assert fresh.timed_out is False


def test_unregister_removes_cancelled_entry_before_sequential_reuse():
    registry = RunControlRegistry()
    first = registry.register("turn-1", deadline_at=time.monotonic() - 1.0)
    registry.request_cancel("turn-1", "first-run")
    registry.unregister("turn-1")

    second = registry.register("turn-1", deadline_at=time.monotonic() + 10.0)
    assert second is not first
    assert second.cancelled is False
    assert second.reason == ""
    assert second.timed_out is False


def test_concurrent_registration_and_cancellation_are_consistent():
    registry = RunControlRegistry()

    def register_and_cancel(index: int):
        turn_id = f"turn-{index % 4}"
        control = registry.register(turn_id, deadline_at=time.monotonic() + 10.0)
        registry.request_cancel(turn_id, f"worker-{index}")
        return control, registry.get(turn_id)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(register_and_cancel, range(128)))

    for control, observed in results:
        assert observed is control
        assert observed.cancelled is True
        assert observed.reason.startswith("worker-")
        assert observed.timed_out is False

    for index in range(4):
        registry.unregister(f"turn-{index}")
        assert registry.get(f"turn-{index}") is None


def test_cancellation_intent_survives_registry_restart(tmp_path):
    path = str(tmp_path / "run_controls.sqlite3")
    first = RunControlRegistry(store_path=path)
    assert first.request_cancel("restart-turn", "operator stopped it") is True

    restarted = RunControlRegistry(store_path=path)
    control = restarted.register("restart-turn")
    assert control.cancelled is True
    assert control.reason == "operator stopped it"

    restarted.unregister("restart-turn")
    fresh = RunControlRegistry(store_path=path)
    assert fresh.register("restart-turn").cancelled is False


def test_running_registry_refreshes_cancellation_from_another_process(tmp_path):
    path = str(tmp_path / "run_controls-cross-process.sqlite3")
    running = RunControlRegistry(store_path=path)
    surface = RunControlRegistry(store_path=path)
    control = running.register("live-turn")
    assert control.cancelled is False

    assert surface.request_cancel("live-turn", "operator stopped it") is True
    assert control.cancelled is False
    assert running.refresh_cancel("live-turn") is True
    assert control.cancelled is True
    assert control.reason == "operator stopped it"


@pytest.mark.asyncio
async def test_live_model_stream_observes_cross_process_cancellation(tmp_path):
    class Brain:
        def stream_generate(self, **_kwargs):
            for index in range(20):
                time.sleep(0.02)
                yield f"chunk-{index}"

    path = str(tmp_path / "run_controls-stream.sqlite3")
    running = RunControlRegistry(store_path=path)
    surface = RunControlRegistry(store_path=path)
    running.register("stream-cross-process")

    host = V5ModelCaller()
    host.brain = Brain()
    host.logger = logging.getLogger("test.v5.model")
    host._current_turn_id = "stream-cross-process"
    host._run_controls = running

    stream = host._stream_model([{"role": "user", "content": "wait"}])
    assert await stream.__anext__() == "chunk-0"
    assert surface.request_cancel("stream-cross-process", "operator stopped stream") is True

    with pytest.raises(asyncio.CancelledError, match="operator stopped stream"):
        await stream.__anext__()
    await stream.aclose()


@pytest.mark.asyncio
async def test_in_flight_tool_wait_observes_cross_process_cancellation(tmp_path):
    path = str(tmp_path / "run_controls-tool.sqlite3")
    running = RunControlRegistry(store_path=path)
    surface = RunControlRegistry(store_path=path)
    running.register("tool-cross-process")

    host = V5ToolExecutor()
    host._current_turn_id = "tool-cross-process"
    host._run_controls = running

    async def slow_operation():
        await asyncio.sleep(2)
        return "unexpected completion"

    pending = asyncio.create_task(host._await_run_budget(slow_operation()))
    await asyncio.sleep(0.08)
    assert surface.request_cancel("tool-cross-process", "operator stopped tool") is True

    with pytest.raises(asyncio.CancelledError, match="operator stopped tool"):
        await asyncio.wait_for(pending, timeout=1.0)


@pytest.mark.asyncio
async def test_safe_model_call_propagates_effective_transport_timeout():
    class Brain:
        def __init__(self):
            self.kwargs = None

        def generate(self, **kwargs):
            self.kwargs = kwargs
            return "ok"

    host = V5ModelCaller()
    host.brain = Brain()
    host.logger = logging.getLogger("test.v5.model")

    assert await host._safe_model_call(
        [{"role": "user", "content": "hello"}], timeout=7.5
    ) == "ok"
    assert host.brain.kwargs["timeout"] == 7.5


@pytest.mark.asyncio
async def test_stream_model_propagates_effective_transport_timeout():
    class Brain:
        def __init__(self):
            self.kwargs = None

        def stream_generate(self, **kwargs):
            self.kwargs = kwargs
            yield "ok"

    host = V5ModelCaller()
    host.brain = Brain()
    host.logger = logging.getLogger("test.v5.model")

    assert [chunk async for chunk in host._stream_model(
        [{"role": "user", "content": "hello"}], timeout=8.5
    )] == ["ok"]
    assert host.brain.kwargs["timeout"] == 8.5


@pytest.mark.asyncio
async def test_stalled_model_stream_observes_parent_deadline():
    class Brain:
        def stream_generate(self, **kwargs):
            while True:
                time.sleep(0.01)
                yield ""

    host = V5ModelCaller()
    host.brain = Brain()
    host._current_turn_id = "stream-turn"
    host._run_controls = RunControlRegistry()
    host._run_controls.register("stream-turn", deadline_at=time.monotonic() + 0.08)

    with pytest.raises(asyncio.TimeoutError):
        async for _ in host._stream_model([{"role": "user", "content": "wait"}]):
            pass
