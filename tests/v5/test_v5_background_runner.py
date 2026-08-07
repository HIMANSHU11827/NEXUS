import asyncio

from orchestrators.v5.background_runner import V5BackgroundRunner


class _Runner(V5BackgroundRunner):
    def __init__(self):
        self.events = []

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
