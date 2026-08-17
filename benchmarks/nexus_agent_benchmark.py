"""Deterministic, provider-independent benchmark for Nexus agent behavior.

This measures framework properties only: replay verdict correctness, canonical
event normalization, planning/tool evidence, and safety classification. It is
not a model IQ score and must not be compared directly with SWE-bench or GAIA
leaderboard percentages.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Support both ``python -m benchmarks.nexus_agent_benchmark`` and the
# documented ``python benchmarks/nexus_agent_benchmark.py`` invocation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nexus.events import CanonicalEvent
from nexus.main_agent.bench import V5Bench
from security.policies.safety_store import _command_policy_for


def _case(name: str, check: Callable[[], tuple[bool, str]]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        passed, evidence = check()
    except Exception as exc:  # benchmark failures are evidence, not crashes
        passed, evidence = False, f"{type(exc).__name__}: {exc}"
    return {
        "name": name,
        "passed": bool(passed),
        "evidence": str(evidence),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _bench_replay_verdicts() -> tuple[bool, str]:
    bench = V5Bench()
    cases = [
        ({"success": True, "actions": [{"success": True, "tool": "read"}]}, True),
        ({"success": True, "actions": [{"success": False, "tool": "write"}]}, False),
        ({"success": True, "actions": {"tool": "read"}}, False),
        ({"success": True, "n_failed": 1, "actions": [{"success": True}]}, False),
    ]
    observed = [bench.evaluate_turn(entry)["success"] for entry, _ in cases]
    expected = [expected for _, expected in cases]
    return observed == expected, f"observed={observed}; expected={expected}"


def _bench_canonical_events() -> tuple[bool, str]:
    events = [
        ({"id": "p", "kind": "todo", "status": "running", "stage": "planning"}, "plan.started"),
        ({"id": "c", "kind": "command", "status": "success", "command": "pwd"}, "command.completed"),
        ({"id": "t", "kind": "tool", "status": "failed", "tool": "terminal"}, "tool.failed"),
    ]
    observed = [CanonicalEvent.from_work_event(event, "bench", i).type for i, (event, _) in enumerate(events, 1)]
    expected = [expected for _, expected in events]
    return observed == expected, f"observed={observed}; expected={expected}"


def _bench_safety_ordering() -> tuple[bool, str]:
    commands = {
        "type .env": "credential_access",
        "cat private.pem": "credential_access",
        "echo ok && type .env": "credential_access",
        "ls -la": "safe_commands",
    }
    observed = {command: _command_policy_for(command)[0] for command in commands}
    return observed == commands, f"observed={observed}; expected={commands}"


def run() -> dict[str, Any]:
    cases = [
        _case("replay_verdict_integrity", _bench_replay_verdicts),
        _case("canonical_event_normalization", _bench_canonical_events),
        _case("safety_rule_precedence", _bench_safety_ordering),
    ]
    passed = sum(1 for item in cases if item["passed"])
    return {
        "benchmark": "nexus-agent-framework-v1",
        "provider_independent": True,
        "timestamp": time.time(),
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases) if cases else 0.0,
        "cases": cases,
        "limitations": [
            "Does not measure model capability or external-task success.",
            "Not directly comparable to SWE-bench, GAIA, or AgentBench leaderboard scores.",
            "Reference repositories were analyzed separately; they were not run with their provider dependencies.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = run()
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
