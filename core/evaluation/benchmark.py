"""Local benchmark runner for NEXUS regression scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import subprocess
import time
from typing import Dict, List, Optional


@dataclass
class BenchmarkCase:
    id: str
    command: str
    expected_contains: str = ""
    timeout: int = 30


@dataclass
class BenchmarkResult:
    id: str
    passed: bool
    duration: float
    command: str
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str = ""


class BenchmarkRunner:
    """Runs deterministic local benchmarks and stores score history."""

    SUITE_VERSION = "2026.04.25-product-gate-failure-vaccine"

    DEFAULT_CASES = [
        BenchmarkCase("compile-core", "python -m compileall -q core orchestrators tools rag knowledge utils dashboard\\api.py nexus.py shell.py"),
        BenchmarkCase("diagnostics-core", "python -c \"from core.code_intelligence.diagnostics import DiagnosticRunner; import sys; r=DiagnosticRunner('.').run(paths=['core','tools/nexus_tools','rag','orchestrators','configs']); print(r); sys.exit(0 if r['ok'] else 1)\""),
        BenchmarkCase("autonomy-tests", "python tests\\test_autonomy.py", "OK"),
        BenchmarkCase("cognition-tests", "python tests\\test_cognition.py", "OK"),
        BenchmarkCase("hardening-tests", "python tests\\test_hardening.py", "OK"),
        BenchmarkCase("nextgen-power-tests", "python tests\\test_nextgen_power.py", "OK"),
        BenchmarkCase("advanced-tools-tests", "python tests\\test_advanced_tools.py", "OK"),
        BenchmarkCase("dashboard-security-tests", "python tests\\test_dashboard_security.py", "OK"),
        BenchmarkCase("provider-routing-tests", "python tests\\test_provider_routing.py", "OK"),
        BenchmarkCase("secret-scanner-tests", "python tests\\test_secret_scanner.py", "OK"),
        BenchmarkCase("legacy-quarantine-tests", "python tests\\test_legacy_quarantine.py", "OK"),
        BenchmarkCase("kernel-core-tests", "python tests\\test_core.py", "OK", timeout=60),
        BenchmarkCase("loop-tests", "python tests\\test_unified_loop.py", "OK", timeout=60),
        BenchmarkCase("genesis-smoke-test", "python tests\\test_genesis.py", "OK"),
        BenchmarkCase("dashboard-build", "cd dashboard && npm run build", "built", timeout=60),
    ]

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.history_path = os.path.join(self.root, "workspace", "benchmark_history.jsonl")
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)

    def run(self, cases: Optional[List[BenchmarkCase]] = None) -> Dict[str, object]:
        selected = cases or self.DEFAULT_CASES
        results = [self._run_case(case) for case in selected]
        score = sum(1 for result in results if result.passed)
        summary = {
            "timestamp": time.time(),
            "suite_version": self.SUITE_VERSION,
            "score": score,
            "total": len(results),
            "pass_rate": score / len(results) if results else 0.0,
            "results": [asdict(result) for result in results],
        }
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
        return summary

    def history(self, limit: int = 20) -> List[Dict[str, object]]:
        if not os.path.exists(self.history_path):
            return []
        with open(self.history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        output: List[Dict[str, object]] = []
        for line in lines:
            try:
                output.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return output

    def _run_case(self, case: BenchmarkCase) -> BenchmarkResult:
        start = time.time()
        try:
            proc = subprocess.run(
                case.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.root,
                timeout=case.timeout,
            )
            combined = f"{proc.stdout}\n{proc.stderr}"
            passed = proc.returncode == 0 and (not case.expected_contains or case.expected_contains in combined)
            return BenchmarkResult(
                id=case.id,
                passed=passed,
                duration=time.time() - start,
                command=case.command,
                stdout_tail=proc.stdout[-2000:],
                stderr_tail=proc.stderr[-2000:],
                error="" if passed else f"returncode={proc.returncode}",
            )
        except subprocess.TimeoutExpired as exc:
            return BenchmarkResult(
                id=case.id,
                passed=False,
                duration=time.time() - start,
                command=case.command,
                error=f"timeout after {case.timeout}s",
                stdout_tail=(exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
                stderr_tail=(exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
            )
