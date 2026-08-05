"""Tests for the long-horizon mission layer (queue/mission.py)."""

import json
import os

import pytest

from queue.mission import (
    MissionRunner,
    MissionStore,
    mission_from_dict,
    mission_to_dict,
)


@pytest.fixture()
def mission_root(tmp_path):
    return str(tmp_path / "data" / "missions")


def make_runner(mission_root, tmp_path):
    q = __import__("queue.store", fromlist=["TaskQueue"]).TaskQueue(
        db_path=str(tmp_path / "queue.db"), root=str(tmp_path)
    )
    return MissionRunner(queue=q, root=str(tmp_path), store=MissionStore(root=mission_root))


def test_create_and_persist_mission(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine", "Globe", "AI", "Ships"])
    assert m.status == "active"
    assert m.total == 4
    # persisted, reloadable
    loaded = MissionStore(root=mission_root).get(m.id)
    assert loaded is not None and loaded.goal == "Build GTA5"
    assert loaded.done_count == 0


def test_roundtrip_dict():
    m = mission_from_dict(
        {"id": "x", "goal": "g", "status": "active", "milestones": [
            {"index": 0, "task_desc": "a", "status": "pending", "attempts": 0,
             "replans": 0, "last_error": "", "last_queued_task_id": None, "done_at": None},
        ]}
    )
    assert m.total == 1
    assert m.goal == "g"


def test_advance_queues_pending_only_once(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine", "Globe"])
    n1 = runner.advance()
    assert n1 == 1                       # one pending queued (limit default4, first mission)
    m2 = runner.store.get(m.id)
    # milestone0 now queued; next_pending skips queued; advance won't double-queue
    n2 = runner.advance()
    assert n2 == 0
    assert m2.milestones[0].status in ("queued", "running")


def test_hydrate_requeues_pending_after_restart(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine", "Globe"])
    runner.advance()
    # new runner instance = "restart"; pending milestones must re-queue
    runner2 = make_runner(mission_root, tmp_path)
    # simulate: first milestone has been leased (running) -> not pending; second still pending
    first = runner2.store.get(m.id).milestones[0]
    first.status = "running"           # a worker leased it before restart
    runner2.store.save(runner2.store.get(m.id))
    n = runner2.hydrate_active()
    assert n == 1                       # only the still-pending one requeued


def test_reconcile_success_completes_milestone(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine", "Globe"])
    runner.advance()
    # fake task returned from the durable queue
    task = {"payload": {"meta": {"mission": m.id, "milestone": 0}}}
    r = runner.reconcile(task, "success")
    assert r.milestones[0].status == "done"
    assert r.done_count == 1
    # second milestone still pending -> mission not complete
    assert r.status == "active"


def test_reconcile_failure_replans_then_blocks(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine"], max_replans=2)
    task = {"payload": {"meta": {"mission": m.id, "milestone": 0}}}
    # fail up to max_replans (2) times -> re-planned AND re-queued each time
    for i in range(2):
        r = runner.reconcile(task, "failure", "boom")
        assert r.milestones[0].status == "queued"   # re-planned, not abandoned
        assert r.milestones[0].replans == i + 1
    # next (3rd) failure exceeds max_replans -> blocked, mission still active
    r = runner.reconcile(task, "failure", "still boom")
    assert r.milestones[0].status == "blocked"
    assert r.milestones[0].replans == 2
    assert r.status == "active"


def test_all_done_completes_mission(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    m = runner.create_mission("Build GTA5", milestones=["Engine", "Globe"])
    for i in range(2):
        task = {"payload": {"meta": {"mission": m.id, "milestone": i}}}
        runner.reconcile(task, "success")
    r = runner.store.get(m.id)
    assert r.status == "completed"
    assert r.completed_at is not None
    assert r.progress() == 1.0


def test_reconcile_ignores_non_mission_tasks(tmp_path, mission_root):
    runner = make_runner(mission_root, tmp_path)
    r = runner.reconcile({"payload": {"meta": {}}}, "success")
    assert r is None


def test_end_to_end_mission_completes_via_driver(tmp_path, mission_root):
    """The full chain: create -> driver leases+executes -> reconcile -> advance
    -> mission completes -> restart-safe ledger."""
    import asyncio

    from queue.driver import QueueDriver

    q = __import__("queue.store", fromlist=["TaskQueue"]).TaskQueue(
        db_path=str(tmp_path / "q.db"), root=str(tmp_path)
    )
    runner = MissionRunner(queue=q, root=str(tmp_path), store=MissionStore(root=mission_root))
    m = runner.create_mission("any task", milestones=["A", "B"])

    class StubLoop:
        def __init__(self):
            self.calls = 0

        def stream_run(self, task_desc, **kw):
            self.calls += 1
            return self._gen()

        async def _gen(self):
            yield {"type": "done", "data": {"success": True, "response": "ok"}}

    loop = StubLoop()

    async def worker_forever():
        d = QueueDriver(queue=q, workers=1, mission_runner=runner, idle_sleep=0.05)
        d._build_loop = lambda *a, **k: loop
        try:
            await asyncio.wait_for(d.run(), timeout=3)
        except asyncio.TimeoutError:
            pass
        d.stop()
        await d.shutdown(drain_timeout=1)

    asyncio.run(worker_forever())
    final = MissionStore(root=mission_root).get(m.id)
    assert loop.calls == 2
    assert final.status == "completed"
    assert [ms.status for ms in final.milestones] == ["done", "done"]
    assert final.progress() == 1.0
    # restart recovery: a fresh store still sees the completed mission
    assert MissionStore(root=mission_root).get(m.id).status == "completed"
