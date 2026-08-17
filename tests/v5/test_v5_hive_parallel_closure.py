"""Regression tests for V5 hive merge + parallel executor closure.

Covers two verified gaps:

1. ``orchestrators/v5/hive.py::_inject_hive_context`` folded the consolidated
   sub-agent result into ``perceived.context_summary``, but ``core.py``
   re-derives ``context_summary`` from the turn's cached memory snapshot
   (core.py:1936-1953) before calling the direct model/tool loop
   (core.py:2050-2051), silently dropping the hive merge.

2. ``orchestrators/v5/parallel.py::_step_action`` was decorated
   ``@staticmethod`` while its body calls ``self._normalise_result``, so every
   ``_run_steps_parallel`` tool step raised ``NameError: name 'self' is not
   defined``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from nexus.main_agent.hive import V5Hive, _HIVE_RESULT_MARKER
from nexus.main_agent.parallel import V5ParallelExecutor


# ─────────────────────────── (a) hive merge ──────────────────────────────


@dataclass
class _MemCtx:
    """Duck-typed stand-in for the MemoryManager prefetch snapshot."""

    session_history: str = ""
    rag_context: str = ""
    failure_vaccines: str = ""
    knowledge_context: str = ""
    episodic: str = ""
    procedural: str = ""


@dataclass
class _Perceived:
    original_input: str = "do the thing"
    context_summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class _HiveHost(V5Hive):
    """Minimal host exposing what ``_inject_hive_context`` touches."""

    logger = logging.getLogger("test.hive")

    def __init__(self, mem_ctx: _MemCtx) -> None:
        turn = SimpleNamespace(metadata={"_memory_context": mem_ctx})
        self.runtime = SimpleNamespace(current_turn=turn)
        self.consolidated = "SUBAGENT FINDING: config key is misspelled"

    def _hive_enabled(self) -> bool:
        return True

    async def _maybe_spawn_hive(self, task_desc, force=False, timeout_seconds=None):
        return self.consolidated


def _core_context_rebuild(ctx: _MemCtx) -> str:
    """Replica of core.py:1944-1953 — the join that overwrote the merge."""
    return "\n".join(
        part
        for part in (
            ctx.session_history,
            ctx.rag_context,
            ctx.failure_vaccines,
            ctx.knowledge_context,
            ctx.episodic,
            ctx.procedural,
        )
        if part
    )[:10000]


def test_hive_result_survives_core_memory_context_rebuild():
    """RED before fix: the rebuilt context_summary lost the [HIVE_RESULT] block."""
    mem_ctx = _MemCtx(session_history="prior turn", rag_context="docs snippet")
    host = _HiveHost(mem_ctx)
    perceived = _Perceived()

    asyncio.run(host._inject_hive_context(perceived))

    # Direct injection still happens (unchanged behaviour).
    assert _HIVE_RESULT_MARKER in perceived.context_summary
    assert "config key is misspelled" in perceived.context_summary

    # And it now survives core's downstream context rebuild.
    rebuilt = _core_context_rebuild(mem_ctx)
    assert _HIVE_RESULT_MARKER in rebuilt
    assert "config key is misspelled" in rebuilt
    # Pre-existing memory content is preserved, not replaced.
    assert "prior turn" in rebuilt and "docs snippet" in rebuilt


def test_hive_preserve_is_idempotent_and_never_raises():
    mem_ctx = _MemCtx()
    host = _HiveHost(mem_ctx)
    perceived = _Perceived()

    asyncio.run(host._inject_hive_context(perceived))
    first = mem_ctx.knowledge_context
    asyncio.run(host._inject_hive_context(perceived))
    assert mem_ctx.knowledge_context == first
    assert mem_ctx.knowledge_context.count(_HIVE_RESULT_MARKER) == 1

    # No runtime / no memory snapshot / bad snapshot must all degrade softly.
    bare = _HiveHost(mem_ctx)
    bare.runtime = None
    bare._hive_preserve_in_memory_context("x")
    bare.runtime = SimpleNamespace(current_turn=SimpleNamespace(metadata=None))
    bare._hive_preserve_in_memory_context("x")
    bare.runtime = SimpleNamespace(current_turn=SimpleNamespace(metadata={}))
    bare._hive_preserve_in_memory_context("x")


# ───────────────────────── (c) parallel executor ──────────────────────────


class _ParallelHost(V5ParallelExecutor):
    logger = logging.getLogger("test.parallel")
    tool_registry = None

    def __init__(self) -> None:
        self.calls = []

    async def _run_tool(self, call):
        self.calls.append(call.name)
        if call.name == "boom":
            raise RuntimeError("tool exploded")
        return {"success": True, "output": f"ran {call.name}"}


def test_run_steps_parallel_executes_without_nameerror():
    """RED before fix: NameError: name 'self' is not defined (parallel.py:93)."""
    host = _ParallelHost()
    actions = asyncio.run(
        host._run_steps_parallel(
            [
                {"description": "read a file", "tool": "reading", "params": {"p": 1}},
                {"description": "think", "tool": "", "params": {}},
                {"description": "write a file", "tool": "writing", "params": {"p": 2}},
            ]
        )
    )
    assert len(actions) == 3
    assert all(a["success"] for a in actions)
    assert actions[0]["tool"] == "reading"
    assert actions[2]["tool"] == "writing"
    assert actions[1]["execution_mode"] == "reasoning"


def test_run_steps_parallel_propagates_tool_errors():
    host = _ParallelHost()
    actions = asyncio.run(
        host._run_steps_parallel(
            [{"description": "explode", "tool": "boom", "params": {}}]
        )
    )
    assert len(actions) == 1
    assert actions[0]["success"] is False
    assert "tool exploded" in actions[0]["error"]


# ───────────────────── (b) stall replan wiring is live ────────────────────


def test_detect_stall_feeds_ledger_history_used_by_replan():
    """Ledger -> _detect_stall -> _hive_replan_on_stall contract holds."""
    from nexus.main_agent.active_loop import V5ActiveLoop

    class _Host(V5ActiveLoop, V5ParallelExecutor):
        logger = logging.getLogger("test.active")
        tool_registry = None

    host = _Host()
    host._init_task_ledger()
    assert host._detect_stall(host._ledger_history()) is False
    for _ in range(3):
        host._ledger_record({"description": "same step", "tool": "t"}, False)
    assert host._detect_stall(host._ledger_history()) is True
    # Replan is a no-op unless active mode is enabled (guarded, never raises).
    assert asyncio.run(host._hive_replan_on_stall(SimpleNamespace(original_input="x"))) is None
