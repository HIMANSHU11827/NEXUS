"""Regression tests for two concrete durable/cron closure gaps.

1. ``V5Cron._task_policy`` shadowed its own method name, so the policy map was
   never a dict: every ``_schedule_task_priority`` call failed and every
   ``_cron_runner`` invocation raised before ``self.run`` was reached.
2. A durable background job with ``retries`` re-entered ``store.claim`` on the
   second attempt, which cannot succeed while the row is already ``running``.
   The retry silently no-opped and the ledger row was stranded in ``running``.
"""

import asyncio
import logging

from nexus.main_agent.background_runner import V5BackgroundRunner
from nexus.main_agent.cron import V5Cron


class _Runner(V5BackgroundRunner):
    def __init__(self, root_dir=None):
        self.events = []
        self.root_dir = str(root_dir) if root_dir else None

    async def _emit_runtime_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _Cron(V5Cron):
    logger = logging.getLogger("test.cron")


def test_cron_task_policy_is_a_real_mutable_map():
    cron = _Cron()
    policy = cron._task_policy()
    assert isinstance(policy, dict)
    policy["cron_x"] = {"priority": 1, "timeout_s": 5.0}
    assert cron._task_policy()["cron_x"]["timeout_s"] == 5.0


def test_cron_runner_reaches_run_with_recorded_timeout_policy():
    calls = []

    class _RunnableCron(_Cron):
        async def run(self, task_desc):
            calls.append(task_desc)
            return "ok"

    cron = _RunnableCron()
    cron._task_policy()["job-1"] = {"priority": 0, "timeout_s": 5.0}
    cron._cron_runner("job-1")
    assert calls == ["job-1"]


def test_durable_retry_records_terminal_failure_instead_of_stranding_running(tmp_path):
    async def scenario():
        runner = _Runner(tmp_path)
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient boom")
            return "second attempt ok"

        task_id = runner.submit_durable_background(
            "test.retry", flaky, timeout_s=5, retries=1
        )
        assert task_id
        await runner._drain_runner_tasks()
        row = runner._durable_background_store().get(task_id)
        assert attempts["n"] == 2
        assert row["status"] == "completed", row
        assert "second attempt ok" in row["result_summary"]

    asyncio.run(scenario())
