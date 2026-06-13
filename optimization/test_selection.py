"""Targeted test selection for code changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
import re
from typing import Dict, Iterable, List, Set

from code_intel.edit_plan import EditPlanner


@dataclass
class TestSelection:
    changed_files: List[str]
    tests: List[str] = field(default_factory=list)
    diagnostics_targets: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    reason: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class TestSelector:
    """Selects the smallest useful verification set for changed files."""

    TEST_PATTERNS = ("test_*.py", "*_test.py")
    STOPWORDS = {
        "test",
        "tests",
        "core",
        "tools",
        "utils",
        "engine",
        "script",
        "module",
        "init",
        "__init__",
    }

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def select(self, changed_files: Iterable[str]) -> TestSelection:
        changed = [self._rel(p) for p in changed_files if p]
        tests = self._discover_tests()
        selected: Set[str] = set()
        reasons: Dict[str, List[str]] = {}
        diagnostics_targets: Set[str] = set()

        for file_path in changed:
            plan = EditPlanner(self.root).plan(file_path)
            diagnostics_targets.update(plan.diagnostics_targets)
            candidates = self._candidates_for(file_path, plan.impacted_files, tests)
            for test in candidates:
                selected.add(test)
                reasons.setdefault(test, []).append(f"matches {file_path}")

        if not selected and tests:
            # Prefer a smoke/core suite rather than everything.
            for preferred in ["tests/test_core.py", "tests/test_hardening.py", "tests/test_nextgen_power.py"]:
                if preferred in tests:
                    selected.add(preferred)
                    reasons.setdefault(preferred, []).append("fallback smoke coverage")
                    break

        commands = [f"python {test}" for test in sorted(selected)]
        return TestSelection(
            changed_files=changed,
            tests=sorted(selected),
            diagnostics_targets=sorted(diagnostics_targets),
            commands=commands,
            reason={k: sorted(v) for k, v in reasons.items()},
        )

    def _discover_tests(self) -> List[str]:
        test_dir = os.path.join(self.root, "tests")
        if not os.path.isdir(test_dir):
            return []
        output: List[str] = []
        for dirpath, dirnames, filenames in os.walk(test_dir):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                if filename.startswith("test_") and filename.endswith(".py"):
                    output.append(os.path.relpath(os.path.join(dirpath, filename), self.root).replace("\\", "/"))
        return sorted(output)

    def _candidates_for(self, file_path: str, impacted_files: List[str], tests: List[str]) -> Set[str]:
        needles = self._needles(file_path, impacted_files)
        scored: List[tuple[int, str]] = []
        for test in tests:
            normalized = test.lower()
            score = 0
            for needle in needles:
                if needle in normalized:
                    score += 3
            abs_test = os.path.join(self.root, test)
            try:
                with open(abs_test, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
            except OSError:
                continue
            for needle in needles:
                if needle.replace("/", ".") in content:
                    score += 3
                elif needle in content:
                    score += 1
            if score >= 3:
                scored.append((score, test))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return {test for _, test in scored[:5]}

    def _needles(self, file_path: str, impacted_files: List[str]) -> Set[str]:
        paths = [file_path, *impacted_files]
        needles: Set[str] = set()
        for path in paths:
            stem = os.path.splitext(path)[0].lower()
            parts = [p for p in re.split(r"[/_.-]+", stem) if len(p) > 2 and p not in self.STOPWORDS]
            needles.update(parts)
            if stem.startswith("core/"):
                needles.add(stem.replace("/", "."))
            if stem.startswith("rag/"):
                needles.add(stem.replace("/", "."))
            basename = os.path.basename(stem)
            if basename:
                needles.add(basename)
        return needles

    def _rel(self, path: str) -> str:
        abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, abs_path]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return os.path.relpath(abs_path, self.root).replace("\\", "/")
