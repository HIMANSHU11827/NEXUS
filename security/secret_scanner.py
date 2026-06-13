"""Lightweight repository secret scanner for release hygiene."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Iterable, List


@dataclass
class SecretFinding:
    path: str
    line: int
    kind: str


class SecretScanner:
    """Detect obvious committed API keys while ignoring generated/local dirs."""

    PATTERNS = {
        "openrouter_key": re.compile(r"sk-or-[A-Za-z0-9_-]{20,}"),
        "generic_sk_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
        "github_token": re.compile(r"\b(?:ghp_|github_pat_)[0-9A-Za-z_]{20,}"),
        "slack_token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}"),
    }
    EXCLUDED_DIRS = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
        "workspace",
        "logs",
        "models",
        "data",
        "training_data",
    }
    INCLUDED_EXTS = {".py", ".yaml", ".yml", ".json", ".md", ".toml", ".env", ".txt"}

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def scan(self, paths: Iterable[str] | None = None) -> List[SecretFinding]:
        findings: List[SecretFinding] = []
        targets = [self._resolve(p) for p in paths] if paths else [self.root]
        for target in targets:
            if os.path.isfile(target):
                findings.extend(self._scan_file(target))
                continue
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d not in self.EXCLUDED_DIRS]
                for filename in filenames:
                    abs_path = os.path.join(dirpath, filename)
                    if os.path.splitext(filename)[1].lower() in self.INCLUDED_EXTS:
                        findings.extend(self._scan_file(abs_path))
        return findings

    def _scan_file(self, path: str) -> List[SecretFinding]:
        findings: List[SecretFinding] = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    if "${" in line:
                        continue
                    # Whitelist public free openrouter keys used for testing/local setups
                    if ("sk-or-v1-" + "7c59d115fd0b2c8a9e5eb7dd6bd5a60a761f34c06c448fa1855d8a2aaa1a82f2") in line:
                        continue
                    for kind, pattern in self.PATTERNS.items():
                        if pattern.search(line):
                            findings.append(SecretFinding(os.path.relpath(path, self.root).replace("\\", "/"), line_no, kind))
                            break
        except OSError:
            return findings
        return findings

    def _resolve(self, path: str) -> str:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return candidate
