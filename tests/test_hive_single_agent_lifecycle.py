import asyncio
import json

import pytest

from hive.engine import NexusHiveEngine


def test_spawn_agent_persists_terminal_hive_status(tmp_path):
    async def scenario():
        engine = NexusHiveEngine(root=str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(lambda _messages: "FINAL ANSWER: complete")
        agent = await engine.spawn_agent("single worker")

        while agent.status in {"pending", "running"}:
            await asyncio.sleep(0)
        await asyncio.sleep(0)

        control_path = tmp_path / ".nexus" / "hive" / "controls" / f"{agent.hive_id}.json"
        status = json.loads(control_path.read_text(encoding="utf-8"))["status"]
        await engine.aclose()
        return agent.status, status

    status, persisted_status = asyncio.run(scenario())
    assert status == "success"
    assert persisted_status == "success"


def test_spawn_agent_persists_cancelled_hive_status(tmp_path):
    async def scenario():
        blocker = asyncio.Event()

        async def llm(_messages):
            await blocker.wait()
            return "unreachable"

        engine = NexusHiveEngine(root=str(tmp_path), max_agent_retries=0)
        engine.set_llm_call(llm)
        agent = await engine.spawn_agent("cancelled worker")
        await asyncio.sleep(0)
        await engine.cancel_hive(agent.hive_id)
        status = json.loads(
            (tmp_path / ".nexus" / "hive" / "controls" / f"{agent.hive_id}.json").read_text(
                encoding="utf-8"
            )
        )["status"]
        blocker.set()
        await engine.aclose()
        return agent.status, status

    status, persisted_status = asyncio.run(scenario())
    assert status == "cancelled"
    assert persisted_status == "cancelled"
