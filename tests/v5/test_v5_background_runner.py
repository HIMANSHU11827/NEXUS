import asyncio

import nexus.main_agent.durable_background as durable_background
from nexus.main_agent.background_runner import V5BackgroundRunner
from nexus.main_agent.durable_background import DurableBackgroundStore


class _Runner(V5BackgroundRunner):
    def __init__(self, root_dir=None):
        self.events = []
        self.root_dir = str(root_dir) if root_dir else None

    async def _emit_runtime_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_priority_sort_uses_task_metadata_and_finished_tasks_are_cleaned():
    async def scenario():
        runner = _Runner()
        low = runner._submit_task_priority("low", lambda: asyncio.sleep(0), priority=20, lane="work")
        high = runner._submit_task_priority("high", lambda: asyncio.sleep(0), priority=1, lane="work")
        assert low and high
        by_id = runner._v5_runner_task_by_id()
        assert runner._runner_sort_key(by_id[high]) < runner._runner_sort_key(by_id[low])
        await runner._drain_runner_tasks()
        await asyncio.sleep(0)
        assert not runner._v5_runner_task_by_id()
        assert not runner._task_meta()
        assert not runner._task_lanes().get("work")

    asyncio.run(scenario())


def test_priority_lane_admission_runs_high_priority_before_queued_low_priority():
    async def scenario():
        runner = _Runner()
        order = []

        async def low():
            order.append("low")

        async def high():
            order.append("high")

        assert runner._submit_task_priority("low", low, priority=20, lane="work")
        assert runner._submit_task_priority("high", high, priority=1, lane="work")
        await runner._drain_runner_tasks()
        assert order == ["high", "low"]

    asyncio.run(scenario())


def test_priority_lane_can_opt_into_bounded_parallel_admission():
    async def scenario():
        runner = _Runner()
        assert runner.configure_priority_lane("parallel", 2) == 2
        active = 0
        peak = 0
        release = asyncio.Event()

        async def work():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1

        assert runner._submit_task_priority("a", work, priority=1, lane="parallel")
        assert runner._submit_task_priority("b", work, priority=2, lane="parallel")
        assert runner._submit_task_priority("c", work, priority=3, lane="parallel")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert peak == 2
        release.set()
        await runner._drain_runner_tasks()

    asyncio.run(scenario())


def test_priority_lane_fairness_bounds_low_priority_wait():
    async def scenario():
        runner = _Runner()
        order = []
        release = asyncio.Event()

        async def first():
            order.append("first")
            release.set()

        async def low():
            order.append("low")

        assert runner.configure_priority_lane("fair", 1, max_wait_admissions=2) == 1
        assert runner._submit_task_priority("first", first, priority=1, lane="fair")
        assert runner._submit_task_priority("low", low, priority=100, lane="fair")
        for index in range(4):
            async def high(index=index):
                order.append(f"high-{index}")
            assert runner._submit_task_priority(
                f"high-{index}", high, priority=0, lane="fair"
            )
        await runner._drain_runner_tasks()
        assert order.index("low") <= order.index("high-2")

    asyncio.run(scenario())


def test_durable_background_job_persists_terminal_state(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)
        calls = []

        async def work():
            calls.append("ran")
            return "done"

        task_id = runner.submit_durable_background("test.work", work, name="durable work")
        assert task_id.startswith("durable_test.work_")
        await runner._drain_runner_tasks()
        row = runner._durable_background_store().get(task_id)
        assert row["status"] == "completed"
        assert row["result_summary"] == "done"
        assert calls == ["ran"]

    asyncio.run(scenario())


def test_durable_background_terminal_values_are_redacted(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)

        async def success():
            return "authorization=sk-test-secret-value"

        async def failure():
            raise RuntimeError("token=secret-token-value-123456")

        success_id = runner.submit_durable_background("test.secret.success", success)
        failure_id = runner.submit_durable_background("test.secret.failure", failure)
        await runner._drain_runner_tasks()
        store = runner._durable_background_store()
        success_row = store.get(success_id)
        failure_row = store.get(failure_id)
        assert success_row["status"] == "completed"
        assert "sk-test-secret-value" not in success_row["result_summary"]
        assert "***REDACTED***" in success_row["result_summary"]
        assert failure_row["status"] == "failed"
        assert "secret-token-value-123456" not in failure_row["last_error"]
        assert "***REDACTED***" in failure_row["last_error"]

    asyncio.run(scenario())


def test_durable_background_rehydrates_interrupted_job_after_restart(tmp_path):
    async def scenario():
        store = DurableBackgroundStore(str(tmp_path))
        store.create("durable_saved", "test.resume", "saved", max_retries=0, timeout_s=2, lane="recovery")

        runner = _Runner(tmp_path)
        calls = []

        async def recovered():
            calls.append("recovered")

        assert runner.register_durable_background_factory("test.resume", recovered)
        await runner._drain_runner_tasks()
        row = store.get("durable_saved")
        assert row["status"] == "completed"
        assert calls == ["recovered"]

        # A fresh runner cannot silently execute a persisted job without its
        # explicit factory registration.
        store.create("durable_unknown", "missing.factory", "unknown")
        fresh = _Runner(tmp_path)
        assert fresh.recover_durable_background_tasks() == []
        assert store.get("durable_unknown")["status"] == "pending"

    asyncio.run(scenario())


def test_durable_recovery_preserves_priority_within_a_lane(tmp_path):
    async def scenario():
        store = DurableBackgroundStore(str(tmp_path))
        store.create("low", "test.low", "low", priority=20, lane="recovery")
        store.create("high", "test.high", "high", priority=1, lane="recovery")
        runner = _Runner(tmp_path)
        order = []

        async def low():
            order.append("low")

        async def high():
            order.append("high")

        # Install both factories before the single recovery pass so startup
        # ordering is tested as a batch, not as two separate registrations.
        runner._v5_durable_background_factories = {
            "test.low": low,
            "test.high": high,
        }
        assert set(runner.recover_durable_background_tasks()) == {"low", "high"}
        await runner._drain_runner_tasks()
        assert order == ["high", "low"]

    asyncio.run(scenario())


def test_durable_recovery_claim_allows_only_one_process_attempt(tmp_path):
    async def scenario():
        store = DurableBackgroundStore(str(tmp_path))
        store.create("one", "test.once", "once")
        calls = []

        async def work():
            calls.append("ran")

        first = _Runner(tmp_path)
        second = _Runner(tmp_path)
        first._v5_durable_background_factories = {"test.once": work}
        second._v5_durable_background_factories = {"test.once": work}
        assert first.recover_durable_background_tasks() == ["one"]
        assert second.recover_durable_background_tasks() == ["one"]
        await first._drain_runner_tasks()
        await second._drain_runner_tasks()
        assert calls == ["ran"]

    asyncio.run(scenario())


def test_registering_another_factory_does_not_interrupt_live_job(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)
        started = asyncio.Event()
        release = asyncio.Event()

        async def live():
            started.set()
            await release.wait()

        async def other():
            return None

        task_id = runner.submit_durable_background("test.live", live, timeout_s=5)
        await asyncio.wait_for(started.wait(), timeout=1)
        assert runner._durable_background_store().get(task_id)["status"] == "running"
        assert runner.register_durable_background_factory("test.other", other)
        assert runner._durable_background_store().get(task_id)["status"] == "running"
        release.set()
        await runner._drain_runner_tasks()

    asyncio.run(scenario())


def test_durable_attempt_fence_rejects_stale_terminal_update(tmp_path):
    store = DurableBackgroundStore(str(tmp_path))
    store.create("fenced", "test.fenced", "fenced")
    assert store.claim("fenced", "owner-a") is True
    with store._connection() as connection:
        connection.execute(
            "UPDATE background_tasks SET owner_pid=? WHERE task_id=?",
            (999999, "fenced"),
        )
    assert store.recover_running() == 1
    assert store.claim("fenced", "owner-b") is True
    assert store.complete("fenced", owner_token="owner-a") is False
    assert store.get("fenced")["status"] == "running"
    assert store.complete("fenced", owner_token="owner-b") is True


def test_durable_recovery_uses_platform_process_liveness_probe(tmp_path, monkeypatch):
    store = DurableBackgroundStore(str(tmp_path))
    store.create("alive", "test.alive", "alive")
    store.create("dead", "test.dead", "dead")
    with store._connection() as connection:
        connection.execute(
            "UPDATE background_tasks SET status='running', owner_pid=? WHERE task_id='alive'",
            (111,),
        )
        connection.execute(
            "UPDATE background_tasks SET status='running', owner_pid=? WHERE task_id='dead'",
            (222,),
        )

    monkeypatch.setattr(
        durable_background,
        "_process_is_alive",
        lambda pid: int(pid) == 111,
    )
    assert store.recover_running() == 1
    assert store.get("alive")["status"] == "running"
    assert store.get("dead")["status"] == "interrupted"


def test_durable_background_renews_heartbeat_and_reclaims_stalled_job(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)
        store = runner._durable_background_store()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def work():
            calls.append("run")
            started.set()
            await release.wait()

        task_id = runner.submit_durable_background("test.watch", work, timeout_s=3)
        assert task_id
        await asyncio.wait_for(started.wait(), timeout=1)
        assert store.get(task_id)["status"] == "running"

        # A live heartbeat means a long-running job is not falsely reclaimed.
        await asyncio.sleep(1.1)
        assert store.get(task_id)["status"] == "running"
        assert store.recover_stalled(stale_after=2) == []

        # Simulate a dead/stalled worker by aging its durable heartbeat.
        with store._connection() as connection:
            connection.execute(
                "UPDATE background_tasks SET heartbeat_at=? WHERE task_id=?",
                (0.0, task_id),
            )
        release.set()
        recovered = await runner.watchdog_durable_background_tasks(stale_after=1)
        assert task_id in recovered
        await runner._drain_runner_tasks()
        assert store.get(task_id)["status"] == "completed"
        assert len(calls) == 2

    asyncio.run(scenario())


def test_durable_watchdog_bounds_noncooperative_cancellation(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)
        store = runner._durable_background_store()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def stubborn():
            calls.append("run")
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Model a subprocess/library that does not stop immediately
                # after cancellation. The watchdog must not wait forever or
                # start a duplicate attempt while this task is still alive.
                await release.wait()

        task_id = runner.submit_durable_background(
            "test.stubborn", stubborn, timeout_s=3
        )
        assert task_id
        await asyncio.wait_for(started.wait(), timeout=1)
        with store._connection() as connection:
            connection.execute(
                "UPDATE background_tasks SET heartbeat_at=? WHERE task_id=?",
                (0.0, task_id),
            )

        recovered = await asyncio.wait_for(
            runner.watchdog_durable_background_tasks(
                stale_after=1, cancel_timeout=0.05
            ),
            timeout=0.5,
        )
        assert recovered == []
        assert calls == ["run"]
        assert not runner._v5_runner_task_by_id()[task_id].done()
        assert store.get(task_id)["status"] == "interrupted"

        release.set()
        await runner._drain_runner_tasks()
        # The old owner is fenced and the stable id is only rehydrated on the
        # next watchdog/recovery pass, never duplicated during cancellation.
        assert calls == ["run"]

    asyncio.run(scenario())
