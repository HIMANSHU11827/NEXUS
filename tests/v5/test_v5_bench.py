"""Test the V5 replay eval harness (orchestrators/v5/bench.py)."""

import json
import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5.bench import V5Bench


def _write_replay(tmp_path, entries):
    """Write JSONL replay entries under tmp_path/.nexus_v5/replays.jsonl."""
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(entry) for entry in entries)
    (replay_dir / "replays.jsonl").write_text(lines + "\n", encoding="utf-8")
    return replay_dir / "replays.jsonl"


def test_load_missing_replay_returns_empty(tmp_path):
    """A missing replay file yields an empty list and never raises."""
    bench = V5Bench(root_dir=str(tmp_path))
    assert bench.load() == []
    assert bench.stats["skipped"] == 0
    assert bench.replay_path == str(tmp_path / ".nexus_v5" / "replays.jsonl")


def test_evaluate_turn_all_actions_success():
    """Truthy success with no failing actions is a pass."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "t1",
        "input": "hello world",
        "success": True,
        "actions": [
            {"success": True, "tool": "read", "output": "first"},
            {"success": True, "tool": "write", "output": "second output"},
        ],
    })
    assert verdict["success"] is True
    assert "succeeded" in verdict["reason"]
    assert "second output" in verdict["evidence"]


def test_evaluate_turn_action_failed_despite_success():
    """Truthy success but a failing action with an error is a fail."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "t2",
        "input": "do the thing",
        "success": True,
        "actions": [
            {"success": True, "tool": "read", "output": "ok"},
            {"success": False, "tool": "shell", "error": "boom: connection refused"},
        ],
    })
    assert verdict["success"] is False
    assert "action failed" in verdict["reason"]
    assert "connection refused" in verdict["evidence"]


def test_evaluate_turn_recorded_failure():
    """Falsy success is a recorded failure with reflection evidence."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "t3",
        "input": "failing task",
        "success": False,
        "reflection": {"root_causes": ["tool timeout"]},
    })
    assert verdict["success"] is False
    assert verdict["reason"] == "recorded failure"
    assert "tool timeout" in verdict["evidence"]


def test_evaluate_turn_missing_success_key():
    """An entry without a success key is conservatively a fail."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({"turn_id": "t4", "input": "no flag"})
    assert verdict["success"] is False
    assert verdict["reason"] == "no success field"


def test_run_aggregates_stats(tmp_path):
    """run() counts 2 passing and 1 failing entry with a 2/3 pass rate."""
    _write_replay(tmp_path, [
        {"turn_id": "p1", "success": True, "actions": [{"success": True, "output": "a"}]},
        {"turn_id": "p2", "success": True, "actions": [{"success": True, "output": "b"}]},
        {"turn_id": "f1", "success": False, "error": "nope"},
    ])
    bench = V5Bench(root_dir=str(tmp_path))
    stats = bench.run()
    assert stats["total"] == 3
    assert stats["passed"] == 2
    assert stats["failed"] == 1
    assert stats["skipped"] == 0
    assert stats["pass_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert stats["duration_s"] >= 0.0


def test_run_skips_malformed_lines(tmp_path):
    """Invalid JSON and non-dict lines are counted in skipped."""
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "replays.jsonl").write_text(
        "{not json}\n"
        + json.dumps({"turn_id": "ok", "success": True})
        + "\n[1, 2, 3]\n",
        encoding="utf-8",
    )
    bench = V5Bench(root_dir=str(tmp_path))
    stats = bench.run()
    assert stats["skipped"] == 2
    assert stats["total"] == 1
    assert stats["passed"] == 1
    assert stats["failed"] == 0


def test_run_explicit_replay_path(tmp_path):
    """An explicit replay_path overrides the default resolution."""
    replay = tmp_path / "custom.jsonl"
    replay.write_text(
        json.dumps({"turn_id": "x1", "success": True}) + "\n",
        encoding="utf-8",
    )
    bench = V5Bench(replay_path=str(replay))
    stats = bench.run()
    assert stats["total"] == 1
    assert stats["passed"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Phase 1 regression tests — fixed V5Bench bugs (items #2–#8)
# ─────────────────────────────────────────────────────────────────────────


def test_evaluate_turn_non_list_actions_fails():
    """Item #2: a non-list ``actions`` field must NOT silently pass."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "nl1",
        "input": "bad actions",
        "success": True,
        "actions": {"tool": "read"},  # dict, not list
    })
    assert verdict["success"] is False
    assert verdict["reason"] == "actions field is not a list"
    assert "dict" in verdict["evidence"]


def test_evaluate_turn_actions_string_fails():
    """Item #2: a string ``actions`` field must NOT silently pass."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "nl2",
        "input": "bad actions",
        "success": True,
        "actions": "read then write",
    })
    assert verdict["success"] is False
    assert verdict["reason"] == "actions field is not a list"


def test_evaluate_turn_action_failed_without_error():
    """Item #3: action with ``success=False`` but no ``error`` must still fail."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "ne1",
        "input": "silent failure",
        "success": True,
        "actions": [
            {"success": True, "tool": "read", "output": "ok"},
            {"success": False, "tool": "write"},  # no error key
        ],
    })
    assert verdict["success"] is False
    assert verdict["reason"] == "action failed despite success flag"
    assert "success=false" in verdict["evidence"]
    assert "write" in verdict["evidence"]


def test_evaluate_turn_n_failed_mismatch():
    """Item #4: ``n_failed > 0`` with ``success=True`` must fail."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "nf1",
        "input": "mismatch",
        "success": True,
        "n_failed": 2,
        "actions": [
            {"success": True, "tool": "read", "output": "ok"},
            {"success": True, "tool": "write", "output": "done"},
        ],
    })
    assert verdict["success"] is False
    assert "n_failed mismatch" in verdict["reason"]
    assert "n_failed=2" in verdict["evidence"]


def test_evaluate_turn_n_failed_zero_passes():
    """Item #4: ``n_failed=0`` with all-passing actions still passes."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "nf2",
        "input": "consistent",
        "success": True,
        "n_failed": 0,
        "actions": [{"success": True, "tool": "read", "output": "ok"}],
    })
    assert verdict["success"] is True


def test_evaluate_turn_non_boolean_success_fails():
    """Item #5: a string ``success`` field is rejected by schema validation."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "nb1",
        "input": "ambiguous success",
        "success": "true",  # string, not bool
    })
    assert verdict["success"] is False
    assert "boolean" in verdict["reason"]


def test_run_idempotent(tmp_path):
    """Item #6: calling ``run()`` twice on the same replay gives identical stats."""
    _write_replay(tmp_path, [
        {"turn_id": "i1", "input": "a", "success": True,
         "actions": [{"success": True, "output": "x"}]},
        {"turn_id": "i2", "input": "b", "success": False, "error": "boom"},
        {"turn_id": "i3", "input": "c", "success": True,
         "actions": [{"success": False, "tool": "write"}]},
    ])
    bench = V5Bench(root_dir=str(tmp_path))
    first = bench.run()
    second = bench.run()
    # duration_s differs across runs, but all other fields must match
    for key in ("total", "passed", "failed", "skipped", "pass_rate"):
        assert first[key] == second[key], f"{key}: {first[key]} != {second[key]}"
    assert first["total"] == 3
    assert first["passed"] == 1
    assert first["failed"] == 2


def test_validate_schema_missing_success():
    """Schema validation catches a missing ``success`` key."""
    ok, reason = V5Bench._validate_schema({"turn_id": "x"})
    assert ok is False
    assert "success" in reason


def test_validate_schema_non_dict():
    """Schema validation rejects non-dict entries."""
    ok, reason = V5Bench._validate_schema("not a dict")
    assert ok is False
    assert "dict" in reason


def test_validate_schema_ok():
    """A well-formed entry passes schema validation."""
    ok, reason = V5Bench._validate_schema({
        "turn_id": "ok", "input": "hi", "success": True,
    })
    assert ok is True
    assert reason == ""


@pytest.mark.parametrize("actions,should_pass", [
    # all pass
    ([{"success": True}, {"success": True}], True),
    # one fails with error
    ([{"success": True}, {"success": False, "error": "x"}], False),
    # one fails without error
    ([{"success": True}, {"success": False}], False),
    # empty actions list
    ([], True),
])
def test_evaluate_turn_action_edge_cases(actions, should_pass):
    """Item #8: parameterized coverage of action success/failure edge cases."""
    bench = V5Bench()
    verdict = bench.evaluate_turn({
        "turn_id": "param",
        "input": "edge case",
        "success": True,
        "actions": actions,
    })
    assert verdict["success"] is should_pass


def test_run_collects_verdicts(tmp_path):
    """``run()`` populates ``self.verdicts`` for downstream Hive analysis."""
    _write_replay(tmp_path, [
        {"turn_id": "v1", "input": "a", "success": True,
         "actions": [{"success": True, "output": "ok"}]},
        {"turn_id": "v2", "input": "b", "success": False, "error": "nope"},
    ])
    bench = V5Bench(root_dir=str(tmp_path))
    bench.run()
    assert len(bench.verdicts) == 2
    assert bench.verdicts[0]["turn_id"] == "v1"
    assert bench.verdicts[0]["success"] is True
    assert bench.verdicts[1]["turn_id"] == "v2"
    assert bench.verdicts[1]["success"] is False



# ─────────────────────────────────────────────────────────────────────────
# Phase 2 tests — Hive-powered agentic harness (items #9–#20)
# ─────────────────────────────────────────────────────────────────────────

from orchestrators.v5.bench import V5HiveBench, _parse_hive_verdict, _format_replay_for_hive


class _MockSubAgent:
    """Minimal stand-in for hive.engine.SubAgent with a preset result."""

    def __init__(self, agent_id, persona, task, result, status="success"):
        self.agent_id = agent_id
        self.persona = persona
        self.task = task
        self.result = result
        self.status = status


class _MockHiveEngine:
    """Mock NexusHiveEngine that returns controlled sub-agent verdicts."""

    def __init__(self, verdict_map=None):
        self._verdict_map = verdict_map or {}
        self._llm_call = None
        self._counter = 0

    def set_llm_call(self, call):
        self._llm_call = call

    def set_tool_registry(self, reg):
        pass

    async def spawn_hive(self, tasks, parent_run_id="", tool_registry=None, max_steps=None):
        hive_id = f"mock_hive_{self._counter}"
        self._counter += 1
        agents = []
        for task_text, persona in tasks:
            result = self._verdict_map.get(persona, "")
            agents.append(_MockSubAgent(
                agent_id=f"mock_{persona}",
                persona=persona,
                task=task_text,
                result=result,
            ))
        return hive_id, agents


def _make_mock_llm():
    """Return an async LLM callable that echoes a fixed response."""
    async def _llm(messages):
        return "VERDICT: PASS\nEVIDENCE: mock evidence"
    return _llm


def test_parse_hive_verdict_pass():
    """_parse_hive_verdict extracts PASS verdict and evidence."""
    result = _parse_hive_verdict("VERDICT: PASS\nEVIDENCE: all good")
    assert result["verdict"] == "PASS"
    assert result["evidence"] == "all good"
    assert result["repair"] == ""


def test_parse_hive_verdict_fail_with_repair():
    """_parse_hive_verdict extracts FAIL verdict, evidence, and repair."""
    result = _parse_hive_verdict(
        "VERDICT: FAIL\nEVIDENCE: bad action\nREPAIR: add retry logic"
    )
    assert result["verdict"] == "FAIL"
    assert result["evidence"] == "bad action"
    assert result["repair"] == "add retry logic"


def test_parse_hive_verdict_empty():
    """Empty text defaults to FAIL with no evidence."""
    result = _parse_hive_verdict("")
    assert result["verdict"] == "FAIL"
    assert result["evidence"] == ""


def test_format_replay_for_hive_includes_key_fields():
    """_format_replay_for_hive includes turn_id, input, and actions."""
    text = _format_replay_for_hive({
        "turn_id": "fmt1",
        "input": "do something",
        "success": True,
        "actions": [{"success": True, "tool": "read", "output": "data"}],
    })
    assert "fmt1" in text
    assert "do something" in text
    assert "read" in text

def test_hive_bench_all_pass(tmp_path):
    """When all Hive agents pass and det passes, Hive verdict is PASS."""
    _write_replay(tmp_path, [
        {"turn_id": "hp1", "input": "ok task", "success": True,
         "actions": [{"success": True, "tool": "read", "output": "done"}]},
    ])
    mock_engine = _MockHiveEngine(verdict_map={
        p: "VERDICT: PASS\nEVIDENCE: looks good"
        for p in ("TESTER", "REVIEWER", "ENGINEER", "RESEARCHER", "PLANNER")
    })
    bench = V5HiveBench(
        root_dir=str(tmp_path), llm_call=_make_mock_llm(),
        hive_engine=mock_engine,
    )
    stats = bench.run()
    assert stats["passed"] == 1
    assert stats["failed"] == 0
    assert len(bench.hive_verdicts) == 1
    assert bench.hive_verdicts[0]["success"] is True


def test_hive_bench_one_agent_fail(tmp_path):
    """One dissenting Hive agent flips the verdict to FAIL."""
    _write_replay(tmp_path, [
        {"turn_id": "hf1", "input": "risky task", "success": True,
         "actions": [{"success": True, "tool": "read", "output": "done"}]},
    ])
    mock_engine = _MockHiveEngine(verdict_map={
        "TESTER": "VERDICT: PASS\nEVIDENCE: ok",
        "REVIEWER": "VERDICT: FAIL\nEVIDENCE: uses shell on protected path",
        "ENGINEER": "VERDICT: PASS\nEVIDENCE: clean\nREPAIR: none needed",
        "RESEARCHER": "VERDICT: PASS\nEVIDENCE: ok",
        "PLANNER": "VERDICT: PASS\nEVIDENCE: ok",
    })
    bench = V5HiveBench(
        root_dir=str(tmp_path), llm_call=_make_mock_llm(),
        hive_engine=mock_engine,
    )
    stats = bench.run()
    assert stats["passed"] == 0
    assert stats["failed"] == 1
    assert bench.hive_verdicts[0]["success"] is False
    assert "REVIEWER" in bench.hive_verdicts[0]["reason"]


def test_hive_bench_det_fail_hive_pass_still_fail(tmp_path):
    """Conservative: det fail + Hive pass → still FAIL."""
    _write_replay(tmp_path, [
        {"turn_id": "hd1", "input": "failed task", "success": False,
         "error": "det failure"},
    ])
    mock_engine = _MockHiveEngine(verdict_map={
        p: "VERDICT: PASS\nEVIDENCE: looks ok"
        for p in ("TESTER", "REVIEWER", "ENGINEER", "RESEARCHER", "PLANNER")
    })
    bench = V5HiveBench(
        root_dir=str(tmp_path), llm_call=_make_mock_llm(),
        hive_engine=mock_engine,
    )
    stats = bench.run()
    assert stats["passed"] == 0
    assert stats["failed"] == 1


def test_hive_bench_extracts_repairs(tmp_path):
    """ENGINEER repair suggestions are collected in self.repairs."""
    _write_replay(tmp_path, [
        {"turn_id": "hr1", "input": "needs fix", "success": True,
         "actions": [{"success": True, "tool": "read", "output": "ok"}]},
    ])
    mock_engine = _MockHiveEngine(verdict_map={
        "TESTER": "VERDICT: PASS\nEVIDENCE: ok",
        "REVIEWER": "VERDICT: PASS\nEVIDENCE: safe",
        "ENGINEER": "VERDICT: FAIL\nEVIDENCE: no error handling\nREPAIR: wrap in try/except",
        "RESEARCHER": "VERDICT: PASS\nEVIDENCE: ok",
        "PLANNER": "VERDICT: PASS\nEVIDENCE: ok",
    })
    bench = V5HiveBench(
        root_dir=str(tmp_path), llm_call=_make_mock_llm(),
        hive_engine=mock_engine,
    )
    bench.run()
    assert len(bench.repairs) == 1
    assert "try/except" in bench.repairs[0]["suggestion"]
    assert bench.repairs[0]["turn_id"] == "hr1"

def test_hive_bench_export_report(tmp_path):
    """export_report writes a JSON file with stats and verdicts."""
    import os
    _write_replay(tmp_path, [
        {"turn_id": "he1", "input": "export test", "success": True,
         "actions": [{"success": True, "tool": "read", "output": "ok"}]},
    ])
    mock_engine = _MockHiveEngine(verdict_map={
        p: "VERDICT: PASS\nEVIDENCE: ok"
        for p in ("TESTER", "REVIEWER", "ENGINEER", "RESEARCHER", "PLANNER")
    })
    bench = V5HiveBench(
        root_dir=str(tmp_path), llm_call=_make_mock_llm(),
        hive_engine=mock_engine,
    )
    bench.run()
    out_path = bench.export_report()
    assert os.path.exists(out_path)
    with open(out_path, encoding="utf-8") as fh:
        report = json.load(fh)
    assert "stats" in report
    assert "hive_verdicts" in report
    assert len(report["hive_verdicts"]) == 1


def test_hive_bench_fallback_no_engine(tmp_path):
    """When hive engine is None, V5HiveBench falls back to deterministic."""
    _write_replay(tmp_path, [
        {"turn_id": "hb1", "input": "fallback", "success": True,
         "actions": [{"success": True, "tool": "read", "output": "ok"}]},
    ])
    bench = V5HiveBench(root_dir=str(tmp_path), llm_call=_make_mock_llm())
    bench._hive_engine = None
    bench._get_hive_engine = lambda: None
    stats = bench.run()
    assert stats["passed"] == 1


def test_hive_enabled_env_toggle():
    """_hive_enabled reads the NEXUS_BENCH_HIVE env var."""
    import os
    old = os.environ.get("NEXUS_BENCH_HIVE")
    try:
        os.environ["NEXUS_BENCH_HIVE"] = "1"
        assert V5HiveBench._hive_enabled() is True
        os.environ["NEXUS_BENCH_HIVE"] = "0"
        assert V5HiveBench._hive_enabled() is False
    finally:
        if old is None:
            os.environ.pop("NEXUS_BENCH_HIVE", None)
        else:
            os.environ["NEXUS_BENCH_HIVE"] = old

