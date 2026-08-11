"""Test V5 bounded self-repair (roadmap item 3) and context compaction (item 11)."""

import json
import asyncio
import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5.context_manager import ContextManager
from orchestrators.v5.core import NexusLoopV5, _DuckPerceived


@pytest.fixture(scope="module")
def loop(tmp_path_factory):
    """One NexusLoopV5 instance shared by the repair tests."""
    root = tmp_path_factory.mktemp("v5_loop")
    instance = NexusLoopV5(root_dir=str(root))
    yield instance


@pytest.fixture
def failed_result() -> dict:
    """A verification-failed PAORR-style result dict."""
    return {
        "success": False,
        "actions": [
            {
                "description": "run tests",
                "tool": "bash",
                "success": False,
                "error": "command exited with code 1",
            },
            {"description": "read file", "success": True, "output": "ok"},
        ],
        "verification": {
            "success": False,
            "verified_actions": 1,
            "total_actions": 2,
            "failed_actions": 1,
            "anomalies": ["test suite failed"],
            "evidence_ok": False,
        },
    }


class _EmptyRegistry:
    """Tool registry with no tools; aliases keep real tool names parseable."""

    def list_tools(self, include_unavailable=True) -> dict:
        return {}


async def test_v5_failure_evidence(loop, failed_result):
    """Failure evidence extracts text; clean and broken inputs return ''."""
    evidence = loop._failure_evidence(failed_result)
    assert isinstance(evidence, str)
    assert evidence
    assert "run tests" in evidence
    assert "command exited with code 1" in evidence
    assert "test suite failed" in evidence
    assert "verification verdict" in evidence
    assert len(evidence) <= 1500

    clean = {
        "success": True,
        "actions": [{"description": "read", "success": True, "output": "fine"}],
        "verification": {"success": True, "failed_actions": 0, "anomalies": []},
    }
    assert loop._failure_evidence(clean) == ""
    assert loop._failure_evidence(None) == ""
    assert loop._failure_evidence("junk") == ""
    assert loop._failure_evidence({"success": False}) == ""


async def test_v5_repair_instruction(loop, failed_result):
    """Repair instruction embeds the evidence; clean results yield ''."""
    instruction = loop._repair_instruction(failed_result, None)
    assert instruction.startswith("\n\nPrevious attempt failed. Fix the root causes below")
    assert "command exited with code 1" in instruction
    assert instruction.endswith("\n")
    assert loop._repair_instruction({"success": True, "actions": []}, None) == ""


async def test_v5_repair_budget(loop):
    """Repair budget gates attempts at 1..max_attempts."""
    assert loop._repair_budget(1, 2) is True
    assert loop._repair_budget(2, 2) is True
    assert loop._repair_budget(3, 2) is False
    assert loop._repair_budget(0, 2) is False
    assert loop._repair_budget(1) is True


async def test_v5_compaction_boundary(tmp_path):
    """Boundary keeps first + tail, drops the oldest, and reports counts."""
    mgr = ContextManager(str(tmp_path))
    messages = [
        {"role": "system" if i == 0 else ("user" if i % 2 else "assistant"),
         "content": f"message {i}"}
        for i in range(40)
    ]
    boundary = mgr._compaction_boundary(messages)
    kept = boundary["kept"]
    dropped = boundary["dropped"]
    assert isinstance(kept, list) and dropped > 0
    assert len(kept) <= max(8, int(40 * 0.83))
    assert kept[0] is messages[0]
    assert dropped == 40 - len(kept)
    assert messages[0] not in kept[1:]

    event = boundary["boundary_event"]
    assert event["event_type"] == "context.compacted"
    assert event["kind"] == "context"
    assert event["part_type"] == "other"
    assert event["status"] == "done"
    assert event["dropped"] == dropped
    assert event["kept"] == len(kept)
    assert event["title"] == "Context compacted"

    guarded = mgr._compaction_boundary("not a list")
    assert guarded == {"kept": "not a list", "dropped": 0, "boundary_event": None}


async def test_context_loading_does_not_block_event_loop(tmp_path, monkeypatch):
    mgr = ContextManager(str(tmp_path))
    original = mgr._load_context_sync

    def slow_load():
        import time

        time.sleep(0.08)
        return original()

    monkeypatch.setattr(mgr, "_load_context_sync", slow_load)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        snapshot = await mgr.load_context()
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

    assert snapshot.files_loaded == []
    assert ticks >= 4


async def test_v5_compact_context(tmp_path):
    """Compaction prepends the boundary marker and degrades safely."""
    mgr = ContextManager(str(tmp_path))
    messages = [
        {"role": "system" if i == 0 else "user", "content": f"message {i}"}
        for i in range(40)
    ]
    compacted = mgr._compact_context(messages)
    assert compacted[0]["role"] == "system"
    assert "[context compacted: 7 earlier messages dropped] [boundary]" in compacted[0]["content"]
    assert len(compacted) == len(messages) - 7 + 1
    assert compacted[-1] is messages[-1]

    assert mgr._compact_context("garbage") == "garbage"
    assert mgr._compact_context([]) == []
    short = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert mgr._compact_context(short) == short


async def test_v5_repair_plan_garbage(loop, monkeypatch, failed_result):
    """Unparseable model output yields [] without raising."""
    monkeypatch.setattr(loop, "tool_registry", _EmptyRegistry())

    async def _garbage(messages, **kwargs):
        return "not json at all"

    monkeypatch.setattr(loop, "_safe_model_call", _garbage)
    perceived = _DuckPerceived("Fix the failing tests in the repo")
    steps = await loop._repair_plan(perceived, failed_result, 1)
    assert steps == []


async def test_v5_repair_plan_valid(loop, monkeypatch, failed_result):
    """A valid JSON plan with known tool names is parsed into steps."""
    monkeypatch.setattr(loop, "tool_registry", _EmptyRegistry())
    plan_json = json.dumps({
        "steps": [
            {"description": "run the test suite", "tool": "bash", "params": {}},
            {"description": "list the repository", "tool": "bash", "params": {}},
        ]
    })

    async def _valid(messages, **kwargs):
        return plan_json

    monkeypatch.setattr(loop, "_safe_model_call", _valid)
    perceived = _DuckPerceived("Fix the failing tests in the repo")
    steps = await loop._repair_plan(perceived, failed_result, 1)
    assert len(steps) == 2
    assert steps[0]["description"] == "run the test suite"
    assert steps[0]["tool"] == "bash"
    assert steps[1]["params"] == {}


async def test_v5_repair_plan_no_evidence(loop, monkeypatch):
    """Clean results skip the model call entirely."""

    async def _boom(messages, **kwargs):
        raise AssertionError("model must not be called without evidence")

    monkeypatch.setattr(loop, "_safe_model_call", _boom)
    perceived = _DuckPerceived("Fix the failing tests in the repo")
    steps = await loop._repair_plan(perceived, {"success": True, "actions": []}, 1)
    assert steps == []
