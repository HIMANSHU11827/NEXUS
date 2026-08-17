import asyncio
import sys
import threading
import time
import types

import pytest

from hive.engine import NexusHiveEngine, SubAgent
from extensions.tools.built_in.hive.scripts.hive import HiveTool


def test_hive_tool_forwards_subagent_events_to_runtime_sink(tmp_path):
    captured = []
    tool = HiveTool(root_dir=str(tmp_path))
    engine = NexusHiveEngine(root=str(tmp_path))
    engine.set_llm_call(lambda _messages: "subagent result")
    tool._hive = engine
    tool.set_runtime_context({
        "work_event_sink": captured.append,
        "turn_id": "turn-hive",
        "session_id": "session-hive",
    })

    result = asyncio.run(tool.execute(task="check the docs", persona="REVIEWER"))

    assert result.success is True
    event_types = [event["event_type"] for event in captured]
    assert "subagent.started" in event_types
    assert "subagent.result" in event_types
    assert "subagent.completed" in event_types
    assert all(event["turn_id"] == "turn-hive" for event in captured)
    assert all(event["visibility"] == "public" for event in captured)


def test_default_sync_router_chat_does_not_block_event_loop(monkeypatch, tmp_path):
    release = threading.Event()

    class FakeRouter:
        def chat(self, _messages):
            release.wait(0.5)
            return "router result"

    router_module = types.ModuleType("nexus.capabilities.intelligence.moe_router")
    router_module.NexusMoERouter = FakeRouter
    monkeypatch.setitem(sys.modules, "nexus.capabilities.intelligence.moe_router", router_module)

    async def scenario():
        agent = SubAgent(
            agent_id="agent-sync",
            task="test sync router",
            persona="TESTER",
            parent_run_id="run-sync",
            root=str(tmp_path),
        )
        asyncio.get_running_loop().call_later(0.02, release.set)
        started = time.monotonic()
        result = await agent._default_llm_call([{"role": "user", "content": "go"}])
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(scenario())

    assert result == "router result"
    assert elapsed < 0.2


def test_spawned_agent_task_is_tracked_then_cleaned(tmp_path):
    async def scenario():
        release = asyncio.Event()

        async def llm_call(_messages):
            await release.wait()
            return "done"

        engine = NexusHiveEngine(root=str(tmp_path))
        engine.set_llm_call(llm_call)
        agent = await engine.spawn_agent("tracked task")
        await asyncio.sleep(0)
        assert engine._agent_tasks[agent.agent_id].done() is False

        release.set()
        while agent.status in ("pending", "running"):
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        return engine, agent

    engine, agent = asyncio.run(scenario())

    assert agent.status == "success"
    assert agent.agent_id not in engine._agent_tasks


def test_consolidate_hive_times_out_and_cleans_tasks(tmp_path):
    async def scenario():
        blocker = asyncio.Event()

        async def llm_call(_messages):
            await blocker.wait()
            return "unreachable"

        engine = NexusHiveEngine(root=str(tmp_path), consolidation_timeout=0.01)
        engine.set_llm_call(llm_call)
        hive_id, agents = await engine.spawn_hive([("slow task", "TESTER")])
        await asyncio.sleep(0)

        with pytest.raises(TimeoutError, match="did not finish"):
            await engine.consolidate_hive(hive_id)
        await asyncio.sleep(0)
        return engine, hive_id, agents

    engine, hive_id, agents = asyncio.run(scenario())

    assert agents[0].status == "cancelled"
    assert hive_id not in engine._hive_tasks
    assert agents[0].agent_id not in engine._agent_tasks


def test_cancelling_consolidation_cancels_owned_hive_tasks(tmp_path):
    async def scenario():
        blocker = asyncio.Event()

        async def llm_call(_messages):
            await blocker.wait()
            return "unreachable"

        engine = NexusHiveEngine(root=str(tmp_path))
        engine.set_llm_call(llm_call)
        hive_id, agents = await engine.spawn_hive([("cancel task", "TESTER")])
        await asyncio.sleep(0)

        consolidation = asyncio.create_task(
            engine.consolidate_hive(hive_id, timeout=1.0)
        )
        await asyncio.sleep(0)
        consolidation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consolidation
        await asyncio.sleep(0)
        return engine, hive_id, agents

    engine, hive_id, agents = asyncio.run(scenario())

    assert agents[0].status == "cancelled"
    assert hive_id not in engine._hive_tasks
    assert agents[0].agent_id not in engine._agent_tasks
