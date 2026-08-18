"""Test selection: map changed source files to the tests that cover them."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from typing import List, Optional, Sequence

logger = logging.getLogger("NEXUS_TEST_SELECTION")

_EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules", "workspace", "knowledge",
    ".pytest_cache", "dist", "build", ".mypy_cache", ".ruff_cache",
}


class TestSelector:
    """Select the tests affected by a set of changed files.

    Selection is two-tier:

    1. Static heuristic: a test file matches a changed file when its path
       follows the "test_<module>.py" / "<module>_test.py" convention or
       when the test source text references the changed file path/module.
    2. Fallback: when pytest is importable, the full test list is collected
       via "pytest --collect-only" and filtered by changed-file references.

    Results are test paths relative to the selector root (posix separators),
    suitable for passing back to pytest.
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(root or ".")
        self._test_files: Optional[List[str]] = None
        logger.info("TestSelector initialized at %s", self.root)

    # ------------------------------------------------------------------ public

    def select(self, changed_files: Sequence[str]) -> List[str]:
        """Alias of select_tests (kept for callers using "select")."""
        return self.select_tests(list(changed_files or []))

    def select_tests(self, changed_files: list) -> list:
        """Return test files (relative posix paths) covering the changes."""
        if not changed_files:
            return []
        normalized = [self._normalize(path) for path in changed_files]
        static = self._select_static(normalized)
        if not static:
            static = self._select_via_pytest(normalized)
        combined = list(dict.fromkeys(static))
        combined.sort()
        logger.info(
            "TestSelector: %d changed file(s) -> %d test(s) selected",
            len(normalized),
            len(combined),
        )
        return combined

    def collect_all_tests(self) -> List[str]:
        """Return every discoverable test file under the root (relative posix)."""
        return [self._to_rel(path) for path in self._discover_test_files()]

    # ------------------------------------------------------------------ helpers

    def _normalize(self, path: str) -> str:
        """Normalize a changed-file path to a rooted posix relative path."""
        text = str(path or "").replace("\\", "/").strip()
        if not text:
            return ""
        if os.path.isabs(text):
            try:
                text = os.path.relpath(os.path.abspath(text), self.root).replace("\\", "/")
            except ValueError:
                text = os.path.basename(text)
        text = text.lstrip("./")
        return text

    def _to_rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.root).replace("\\", "/")
        except ValueError:
            return path.replace("\\", "/")

    def _discover_test_files(self) -> List[str]:
        """Walk the root for test modules (cached)."""
        if self._test_files is not None:
            return self._test_files
        found: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                stem = filename[: -len(".py")]
                if stem.startswith("test_") or stem.endswith("_test"):
                    found.append(os.path.join(dirpath, filename))
        found.sort()
        self._test_files = found
        return found

    def _select_static(self, changed: List[str]) -> List[str]:
        """Match test files by naming convention and source references."""
        matches: List[str] = []
        cache: dict = {}
        for test_path in self._discover_test_files():
            rel = self._to_rel(test_path)
            stem = os.path.splitext(os.path.basename(rel))[0]
            hit = False
            for ch in changed:
                if not ch:
                    continue
                ch_stem = os.path.splitext(os.path.basename(ch))[0]
                if stem == "test_" + ch_stem or stem == ch_stem + "_test":
                    hit = True
                    break
                if stem.startswith("test_") and ch_stem in stem:
                    hit = True
                    break
                if ch in rel or ch_stem in rel:
                    hit = True
                    break
            if not hit:
                try:
                    source = cache.get(test_path)
                    if source is None:
                        with open(test_path, "r", encoding="utf-8", errors="ignore") as handle:
                            source = handle.read()
                        cache[test_path] = source
                    for ch in changed:
                        if ch and (ch in source or os.path.basename(ch) in source):
                            hit = True
                            break
                except OSError:
                    continue
            if hit:
                matches.append(rel)
        return matches

    def _pytest_available(self) -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("pytest") is not None
        except Exception:
            return False

    def _select_via_pytest(self, changed: List[str]) -> List[str]:
        """Collect tests with pytest --collect-only and filter by references."""
        if not self._pytest_available():
            logger.info("TestSelector: pytest unavailable, skipping collect-only fallback")
            return []
        tests_dir = os.path.join(self.root, "tests")
        if not os.path.isdir(tests_dir):
            tests_dir = self.root
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header", tests_dir],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            logger.warning("TestSelector: pytest --collect-only failed", exc_info=True)
            return []
        collected = self._parse_collected(proc.stdout or "")
        matches: List[str] = []
        for path in collected:
            rel = self._normalize(path)
            if not rel:
                continue
            for ch in changed:
                if not ch:
                    continue
                ch_stem = os.path.splitext(os.path.basename(ch))[0]
                if ch in rel or ch_stem in rel or ch_stem in os.path.basename(rel):
                    matches.append(rel)
                    break
        return matches

    @staticmethod
    def _parse_collected(stdout: str) -> List[str]:
        """Extract unique test file paths from pytest --collect-only output."""
        paths: List[str] = []
        pattern = re.compile(r"([A-Za-z]:[\\/][^\\s:]+|[\\/]?[^\\s:]+)\\.py::")
        for line in stdout.splitlines():
            match = pattern.search(line)
            if match:
                paths.append(match.group(1) + ".py")
        unique: List[str] = []
        for path in paths:
            if path not in unique:
                unique.append(path)
        return unique


__all__ = ["TestSelector"]
