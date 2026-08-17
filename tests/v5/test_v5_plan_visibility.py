"""Test V5 plan visibility, plan-level approval gating and run.finished telemetry.

Mirrors the collection pattern of ``tests/v5/test_v5_loop.py``: plain
``async def test_*`` functions run via pytest-asyncio (``asyncio_mode =
"auto"`` in pyproject.toml).
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.paorr import PAORREnhanced


async def test_v5_plan_event_emission():
    """plan.updated events carry the plan part type and a step checklist."""
    with TemporaryDirectory() as tmp:
        loop = NexusLoopV5(root_dir=tmp, session_id="plan_visibility_test")
        captured = []

        async def fake_sink(payload):
            captured.append(payload)

        loop.set_work_event_sink(fake_sink)
        loop._current_turn_id = "turn_1"
        await loop._emit_plan_event(
            "pending",
            plan_id="p1",
            goal="Fix the bug",
            total=3,
            steps=["read code", "patch", "verify"],
        )
        event = captured[-1]
        assert event["part_type"] == "plan"
        assert event["event_type"] == "plan.updated"
        assert event["kind"] == "plan"
        assert event["status"] == "pending"
        assert event["title"] == "Plan pending"
        assert event["payload"]["goal"] == "Fix the bug"
        assert event["payload"]["total"] == 3
        assert event["payload"]["steps"] == [
            {"index": 1, "description": "read code"},
            {"index": 2, "description": "patch"},
            {"index": 3, "description": "verify"},
        ]


async def test_tool_progress_exposes_safe_result_and_retry_fields():
    with TemporaryDirectory() as tmp:
        loop = NexusLoopV5(root_dir=tmp, session_id="progress_visibility")
        captured = []
        loop.set_work_event_sink(lambda payload: captured.append(payload))
        loop._current_turn_id = "turn_progress"
        call = SimpleNamespace(
            name="creating", params={"path": "game.py"}, call_id="call_1"
        )

        await loop._emit_tool_progress(
            call, "finished", "failed",
            retry_reason="bad token sk-abcdefghijklmnopqrstuvwxyz123456",
            plan_link={"plan_id": "plan_1", "step_id": "step_1"},
        )

        payload = captured[-1]["payload"]
        assert payload["projection"] == "deterministic-v1"
        assert payload["phase"] == "tool_result"
        assert payload["outcome"] == "failed"
        assert payload["next_action"] == "retry_or_stop"
        assert payload["plan_id"] == "plan_1"
        assert payload["step_id"] == "step_1"
        assert "abcdefghijklmnopqrstuvwxyz123456" not in payload["retry_reason"]


async def test_tool_batch_progress_uses_deterministic_public_projection():
    with TemporaryDirectory() as tmp:
        loop = NexusLoopV5(root_dir=tmp, session_id="batch_progress_visibility")
        captured = []
        loop.set_work_event_sink(lambda payload: captured.append(payload))
        loop._current_turn_id = "turn_batch_progress"

        await loop._emit_tool_batch_progress([
            {"name": "reading", "params": {"path": "README.md"}, "call_id": "read_1", "success": True},
            {"name": "code_search", "params": {"pattern": "Nexus"}, "call_id": "search_1", "success": True},
        ])

        event = captured[-1]
        assert event["event_type"] == "assistant.progress"
        assert event["payload"]["projection"] == "deterministic-v1"
        assert event["payload"]["current_action"]
        assert event["payload"]["outcome"] == "success"


async def test_v5_plan_approval_skipped_outside_approve_mode():
    """The plan approval gate passes immediately outside APPROVE mode."""
    with TemporaryDirectory() as tmp:
        loop = NexusLoopV5(root_dir=tmp, session_id="plan_approval_test")
        loop._permission_mode = lambda: "BYPASS"
        approved = await loop._request_plan_approval(
            "Fix the bug",
            [{"description": "inspect", "tool": "bash", "params": {}}],
        )
        assert approved is True


async def test_v5_paorr_denied_plan_runs_no_tools():
    """A denied approval gate yields failure with zero tool execution."""
    with TemporaryDirectory() as tmp:

        async def fake_planner(perceived):
            return [
                {"description": "step one", "tool": "bash", "params": {}},
                {"description": "step two", "tool": "read_file", "params": {}},
            ]

        async def fake_executor(call):
            raise AssertionError("tool executor must never run on a denied plan")

        seen = []

        async def fake_gate(steps, goal):
            seen.append((steps, goal))
            return False

        paorr = PAORREnhanced(
            root_dir=tmp,
            planner=fake_planner,
            tool_executor=fake_executor,
            approval_gate=fake_gate,
        )
        perceived = SimpleNamespace(
            original_input="user task", intent=SimpleNamespace(value="task")
        )
        result = await paorr.execute(perceived)

        assert seen and seen[0][1] == "user task"
        assert [s["description"] for s in seen[0][0]] == ["step one", "step two"]
        assert result["success"] is False
        assert result["actions"] == []
        assert result["observation"]["anomalies"] == ["plan not approved"]
        assert result["reflection"]["root_causes"] == ["plan rejected by user"]
        assert result["plan"].approved is False
        assert result["plan"].steps == []
        assert result["plan"].goal == "user task"


async def test_v5_paorr_approval_error_fails_closed_without_tools():
    """A broken configured approval gate must never authorize execution."""
    with TemporaryDirectory() as tmp:

        async def fake_planner(_perceived):
            return [{"description": "dangerous step", "tool": "bash", "params": {}}]

        async def failing_gate(_steps, _goal):
            raise RuntimeError("approval surface unavailable")

        async def fake_executor(_call):
            raise AssertionError("tool executor must not run after approval failure")

        paorr = PAORREnhanced(
            root_dir=tmp,
            planner=fake_planner,
            tool_executor=fake_executor,
            approval_gate=failing_gate,
        )
        perceived = SimpleNamespace(
            original_input="user task", intent=SimpleNamespace(value="task")
        )
        result = await paorr.execute(perceived)

        assert result["success"] is False
        assert result["actions"] == []
        assert result["plan"].approved is False


async def test_v5_paorr_plan_emitter_tracks_steps():
    """plan_emitter receives running/done per step plus a plan-level done."""
    with TemporaryDirectory() as tmp:

        async def fake_planner(perceived):
            return [{"description": "step one", "tool": "bash", "params": {}}]

        async def fake_executor(call):
            return "ok"

        updates = []

        async def fake_plan_emitter(status, step_index, description, plan_id):
            updates.append((status, step_index, description, plan_id))

        paorr = PAORREnhanced(
            root_dir=tmp,
            planner=fake_planner,
            tool_executor=fake_executor,
            plan_emitter=fake_plan_emitter,
        )
        perceived = SimpleNamespace(
            original_input="user task", intent=SimpleNamespace(value="task")
        )
        result = await paorr.execute(perceived)

        assert [u[0] for u in updates] == ["running", "done", "done"]
        assert updates[0][1] == 0
        assert updates[0][2] == "step one"
        assert updates[-1][1] is None
        assert len({u[3] for u in updates}) == 1
        assert result["success"] is True


async def test_v5_run_finished_telemetry_payload():
    """run.finished carries the budget/cost telemetry payload verbatim."""
    with TemporaryDirectory() as tmp:
        loop = NexusLoopV5(root_dir=tmp, session_id="run_finished_test")
        captured = []
        loop.set_work_event_sink(lambda payload: captured.append(payload))
        await loop._emit_run_finished(
            "done",
            payload={
                "cost": 0.042,
                "tokens": 1234,
                "duration_ms": 5210.5,
                "attempts": 2,
            },
        )
        event = captured[-1]
        assert event["event_type"] == "run.finished"
        assert event["kind"] == "run"
        assert event["part_type"] == "run"
        assert event["title"] == "Run finished"
        assert event["status"] == "done"
        assert event["payload"]["cost"] == 0.042
        assert event["payload"]["tokens"] == 1234
        assert event["payload"]["duration_ms"] == 5210.5
        assert event["payload"]["attempts"] == 2
