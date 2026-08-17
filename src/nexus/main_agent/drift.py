"""Deterministic user-direction drift checks for the V5 execution boundary."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_STOPWORDS = frozenset({
    "about", "after", "again", "also", "been", "being", "could", "from",
    "have", "into", "just", "make", "more", "must", "only", "please",
    "should", "some", "that", "than", "their", "them", "then", "there",
    "this", "those", "through", "using", "want", "what", "when", "where",
    "which", "with", "would", "your", "task", "work", "user", "agent",
})
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{3,}")


def _tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    return {
        token for token in _TOKEN.findall(text)
        if token not in _STOPWORDS and not token.isdigit()
    }


def _text_from_plan(plan: Any) -> str:
    if isinstance(plan, dict):
        parts = [str(plan.get("goal") or "")]
        steps = plan.get("steps") or []
    else:
        parts = []
        steps = getattr(plan, "steps", None) or []
    for step in steps:
        if isinstance(step, dict):
            parts.extend(str(step.get(key) or "") for key in ("description", "tool", "params"))
        else:
            parts.append(str(step))
    return " ".join(parts)


def assess_direction(goal: str, plan: Any, actions: Iterable[Any] = ()) -> Dict[str, Any]:
    """Assess whether an active plan still reflects the user objective.

    This is intentionally a conservative lexical guard, not an LLM judge:
    it blocks only a plan with zero distinctive-anchor overlap with the goal.
    A non-empty overlap is reported for observability but never treated as
    proof of semantic correctness.
    """
    goal_tokens = _tokens(goal)
    plan_text = _text_from_plan(plan)
    plan_tokens = _tokens(plan_text)
    overlap = sorted(goal_tokens & plan_tokens)
    missing = sorted(goal_tokens - plan_tokens)
    drifted = bool(goal_tokens) and bool(plan_text.strip()) and not overlap
    action_text = " ".join(
        str(item.get(key) or "")
        for item in (actions or [])
        if isinstance(item, dict)
        for key in ("description", "tool", "output")
    )
    return {
        "drifted": drifted,
        "confidence": "low" if drifted else ("partial" if missing else "aligned"),
        "goal_anchors": sorted(goal_tokens),
        "matched_anchors": overlap,
        "missing_anchors": missing,
        "plan_tokens": sorted(plan_tokens),
        "action_evidence_present": bool(action_text.strip()),
        "reason": (
            "active plan has no distinctive lexical anchor in the user objective"
            if drifted else "active plan retains at least one objective anchor; semantic review remains required"
        ),
    }


__all__ = ["assess_direction"]
