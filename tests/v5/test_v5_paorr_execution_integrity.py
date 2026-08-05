"""Focused regressions for PAORR scheduling and evidence verification."""

import asyncio

from orchestrators.v5.paorr import PAORREnhanced, Plan, PlanStep
from orchestrators.v5.verification import V5Verifier


def test_failed_step_does_not_spin_and_blocks_dependents():
    calls = []

    async def execute(call):
        calls.append(call.name)
        raise RuntimeError("compiler failed")

    async def run():
        loop = PAORREnhanced(".", tool_executor=execute)
        plan = Plan(
            plan_id="p1",
            goal="build site",
            confidence=1.0,
            steps=[
                PlanStep("build", "compile site", tool="terminal"),
                PlanStep("test", "run tests", dependencies=["build"], tool="test_runner"),
            ],
        )
        actions = await loop._act(plan)
        return calls, actions

    calls, actions = asyncio.run(run())
    assert calls == ["terminal"]
    assert len(actions) == 2
    assert all(action.success is False for action in actions)
    assert "blocked by" in (actions[1].error or "")


def test_verifier_rejects_plan_with_missing_action_evidence():
    verifier = V5Verifier()
    result = {
        "success": True,
        "plan": {"steps": [{"description": "write"}, {"description": "test"}]},
        "actions": [{"success": True, "output": "written"}],
    }

    verified = asyncio.run(verifier._verify_result(result))
    assert verified["success"] is False
    assert verified["verification"]["success"] is False
    assert verified["verification"]["failed_actions"] == 1
    assert "no action result" in verified["verification"]["anomalies"][0]


def test_paorr_never_simulates_missing_execution():
    async def run():
        loop = PAORREnhanced(".", tool_executor=None)
        loop.tool_registry = None
        return await loop._execute_step(
            PlanStep("build", "build the site", tool="terminal")
        )

    action = asyncio.run(run())
    assert action.success is False
    assert action.resources_used["execution_mode"] == "unavailable"
    assert "no tool executor" in (action.error or "")
    assert "Completed" not in action.output


def test_paorr_plan_emits_failed_terminal_status_after_action_failure():
    updates = []

    async def execute(call):
        raise RuntimeError("tool failed")

    async def emit(status, step_index, description, plan_id):
        updates.append((status, step_index, description))

    async def run():
        loop = PAORREnhanced(".", tool_executor=execute, plan_emitter=emit)
        plan = Plan(
            plan_id="failed-plan",
            goal="test failure",
            confidence=1.0,
            steps=[PlanStep("step", "run tool", tool="terminal")],
        )
        return await loop._act(plan)

    actions = asyncio.run(run())
    assert actions[0].success is False
    assert updates[-1][0] == "failed"
    assert updates[-1][1] is None
    assert updates[-1][2] == "plan failed"
