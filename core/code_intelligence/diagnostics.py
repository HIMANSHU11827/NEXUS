"""Project diagnostics runner for coding-agent verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import py_compile
import subprocess
import time
from typing import Dict, Iterable, List

from core.nexus_compat import import_yaml

_yaml = import_yaml()


@dataclass
class Diagnostic:
    path: str
    kind: str
    ok: bool
    message: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class DiagnosticRunner:
    """Runs deterministic local diagnostics without importing project modules."""

    EXCLUDE_DIRS = {
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
    SUPPORTED_EXTS = {".py", ".json", ".yaml", ".yml"}

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def run(self, paths: Iterable[str] | None = None, include_dashboard: bool = False) -> Dict[str, object]:
        diagnostics: List[Diagnostic] = []
        targets = list(paths or [])
        files = self._collect_files(targets) if targets else self._collect_files(["."])
        for path in files:
            diagnostics.append(self._check_file(path))
        if include_dashboard:
            diagnostics.append(self._check_dashboard_build())
        failed = [d for d in diagnostics if not d.ok]
        return {
            "ok": not failed,
            "total": len(diagnostics),
            "failed": len(failed),
            "diagnostics": [d.to_dict() for d in diagnostics],
        }

    def _collect_files(self, paths: Iterable[str]) -> List[str]:
        collected: List[str] = []
        for item in paths:
            abs_path = self._resolve(item)
            if os.path.isfile(abs_path):
                if os.path.splitext(abs_path)[1].lower() in self.SUPPORTED_EXTS:
                    collected.append(abs_path)
                continue
            if os.path.isdir(abs_path):
                for dirpath, dirnames, filenames in os.walk(abs_path):
                    dirnames[:] = [d for d in dirnames if d not in self.EXCLUDE_DIRS]
                    for filename in filenames:
                        if os.path.splitext(filename)[1].lower() in self.SUPPORTED_EXTS:
                            collected.append(os.path.join(dirpath, filename))
        return sorted(set(collected))

    def _check_file(self, abs_path: str) -> Diagnostic:
        rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
        ext = os.path.splitext(abs_path)[1].lower()
        start = time.time()
        try:
            if ext == ".py":
                py_compile.compile(abs_path, doraise=True)
                return Diagnostic(rel, "python_compile", True, duration_ms=self._elapsed(start))
            with open(abs_path, "r", encoding="utf-8") as f:
                if ext == ".json":
                    json.load(f)
                    return Diagnostic(rel, "json_parse", True, duration_ms=self._elapsed(start))
                _yaml.safe_load(f)
                return Diagnostic(rel, "yaml_parse", True, duration_ms=self._elapsed(start))
        except Exception as exc:
            kind = {".py": "python_compile", ".json": "json_parse"}.get(ext, "yaml_parse")
            return Diagnostic(rel, kind, False, str(exc)[:1000], self._elapsed(start))

    def _check_dashboard_build(self) -> Diagnostic:
        start = time.time()
        dashboard = os.path.join(self.root, "dashboard")
        if not os.path.isdir(dashboard):
            return Diagnostic("dashboard", "dashboard_build", False, "dashboard directory missing", self._elapsed(start))
        try:
            proc = subprocess.run(
                "npm run build",
                cwd=dashboard,
                shell=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
            output = f"{proc.stdout}\n{proc.stderr}"[-2000:]
            return Diagnostic("dashboard", "dashboard_build", proc.returncode == 0, output if proc.returncode else "", self._elapsed(start))
        except Exception as exc:
            return Diagnostic("dashboard", "dashboard_build", False, str(exc)[:1000], self._elapsed(start))

    def _resolve(self, path: str) -> str:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return candidate

    @staticmethod
    def _elapsed(start: float) -> float:
        return round((time.time() - start) * 1000, 2)
