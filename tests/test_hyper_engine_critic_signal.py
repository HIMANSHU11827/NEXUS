"""Regression: the critic's replan/confidence signal must reach the plan.

Before this test, ``HyperReasoningEngine.plan``/``aplan`` computed
``uncertainty`` BEFORE running the critic and reset ``_last_critic_signal``
at the top of the call, so both the parsed ``should_replan`` flag and the
critic ``confidence`` (hyper_engine.py:375) and the critiques list itself
were stored and never read back into the returned ``ReasoningPlan``.
"""

from __future__ import annotations

import asyncio
import json

from nexus.capabilities.reasoning.hyper_engine import HyperReasoningEngine


PLAN_JSON = json.dumps({
    "rationale": "do the thing",
    "steps": [
        {"id": "a", "objective": "inspect code", "suggested_tool": "grep",
         "risk": "low", "verifier": "files found"},
        {"id": "b", "objective": "summarize", "suggested_tool": "final",
         "risk": "low", "verifier": "evidence cited"},
    ],
})

CRITIC_JSON = json.dumps({
    "critiques": ["no verification step", "scope too broad"],
    "should_replan": True,
    "confidence": 0.05,
})


def _engine() -> HyperReasoningEngine:
    def llm_call(system_prompt: str, user_prompt: str) -> str:
        if "critic" in system_prompt.lower():
            return CRITIC_JSON
        return PLAN_JSON

    return HyperReasoningEngine(llm_call=llm_call)


def test_plan_exposes_critic_replan_signal() -> None:
    plan = _engine().plan("check the loader")
    assert plan.critiques == ["no verification step", "scope too broad"]
    # The critic explicitly asked for a replan; the plan must carry it.
    assert plan.should_replan is True
    # confidence 0.05 -> uncertainty at least 0.95 (capped)
    assert plan.uncertainty >= 0.9


def test_aplan_exposes_critic_replan_signal() -> None:
    plan = asyncio.run(_engine().aplan("check the loader"))
    assert plan.should_replan is True
    assert plan.uncertainty >= 0.9


def test_sound_plan_does_not_request_replan() -> None:
    def llm_call(system_prompt: str, user_prompt: str) -> str:
        if "critic" in system_prompt.lower():
            return json.dumps(
                {"critiques": [], "should_replan": False, "confidence": 0.9}
            )
        return PLAN_JSON

    plan = HyperReasoningEngine(llm_call=llm_call).plan("check the loader")
    assert plan.should_replan is False
    assert plan.critiques == []
