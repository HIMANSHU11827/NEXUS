import asyncio
import json

import pytest

from hive.engine import NexusHiveEngine


def test_hive_pause_is_durable_and_resume_releases_safe_boundary(tmp_path):
    async def scenario():
        first_response = asyncio.Event()
        allow_after_first = asyncio.Event()
        second_call = asyncio.Event()
        calls = 0

        async def llm(messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_response.set()
                await allow_after_first.wait()
                return '<tool_call>{"tool":"echo","params":{"value":"ok"}}</tool_call>'
            second_call.set()
            return "FINAL ANSWER: resumed"

        engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(llm)
        hive_id, agents = await engine.spawn_hive(
            [("pause and continue", "WORKER")],
            tool_registry={"echo": lambda value: value},
        )
        await asyncio.wait_for(first_response.wait(), 1)
        await engine.pause_hive(hive_id, "maintenance window")
        allow_after_first.set()

        with open(tmp_path / ".nexus" / "hive" / "controls" / f"{hive_id}.json", encoding="utf-8") as handle:
            assert json.load(handle)["status"] == "paused"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(second_call.wait(), 0.05)

        await engine.resume_hive(hive_id)
        await asyncio.wait_for(second_call.wait(), 1)
        await engine.consolidate_hive(hive_id, timeout=1)
        assert agents[0].status == "success"
        await engine.aclose()

    asyncio.run(scenario())


def test_stale_agent_is_restarted_with_same_identity_and_checkpoint(tmp_path):
    async def scenario():
        blocker = asyncio.Event()

        async def llm(messages):
            await blocker.wait()
            return "FINAL ANSWER: never reached"

        engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(llm)
        hive_id, agents = await engine.spawn_hive([("recover me", "WORKER")])
        agent = agents[0]
        await asyncio.sleep(0.01)
        agent.last_heartbeat -= 100

        replaced = await engine.recover_stuck_agents(stale_after=1, hive_id=hive_id)
        assert replaced == [agent.agent_id]
        assert agent.replacement_count == 1
        assert agent.agent_id in engine._agent_tasks
        assert agent.status in {"pending", "running"}

        await engine.cancel_hive(hive_id)
        blocker.set()
        await engine.aclose()

    asyncio.run(scenario())


def test_hive_agent_honors_durable_cross_process_cancellation(tmp_path):
    async def scenario():
        engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(lambda _messages: "unused")
        hive_id, agents = await engine.spawn_hive([("cancel me", "WORKER")])
        # Simulate another server process writing the operator decision.
        path = tmp_path / ".nexus" / "hive" / "controls" / f"{hive_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "cancelled"
        payload["reason"] = "remote operator cancellation"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(asyncio.CancelledError):
            await engine._wait_for_hive_resume(hive_id, agents[0])
        assert agents[0].status == "cancelled"
        await engine.aclose()

    asyncio.run(scenario())


def test_cancel_hive_persists_before_waiting_for_local_workers(tmp_path):
    async def scenario():
        running = asyncio.Event()
        cancelled_persisted = asyncio.Event()

        async def llm(_messages):
            running.set()
            await asyncio.Event().wait()

        engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(llm)
        hive_id, _agents = await engine.spawn_hive([("long work", "WORKER")])
        await asyncio.wait_for(running.wait(), 1)

        original_persist = engine._persist_hive_control

        def persist(hive, status, reason=""):
            original_persist(hive, status, reason)
            if status == "cancelled":
                cancelled_persisted.set()

        engine._persist_hive_control = persist
        cancellation = asyncio.create_task(engine.cancel_hive(hive_id))
        await asyncio.wait_for(cancelled_persisted.wait(), 1)

        control_path = tmp_path / ".nexus" / "hive" / "controls" / f"{hive_id}.json"
        assert json.loads(control_path.read_text(encoding="utf-8"))["status"] == "cancelled"
        await asyncio.wait_for(cancellation, 1)
        await engine.aclose()

    asyncio.run(scenario())
