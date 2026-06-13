"""Symbol-aware edit planning for safer multi-file code changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Dict, List

from code_intel.repo_map import RepoMapBuilder
from code_intel.side_effects import SideEffectAnalyzer


@dataclass
class EditPlan:
    target: str
    exists: bool
    language: str = "unknown"
    symbols: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    impacted_files: List[str] = field(default_factory=list)
    diagnostics_targets: List[str] = field(default_factory=list)
    recommended_checks: List[str] = field(default_factory=list)
    risk: str = "low"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class EditPlanner:
    """Builds a pre-edit plan from repo map and import blast radius."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def plan(self, target: str) -> EditPlan:
        rel = target.replace("\\", "/")
        abs_path = self._resolve(rel)
        repo = RepoMapBuilder(self.root).build()
        node = next((f for f in repo.files if f.path == rel), None)
        side_effects = SideEffectAnalyzer(self.root).analyze(rel) if os.path.exists(abs_path) else None
        impacted = side_effects.impacted_files if side_effects else []
        diagnostics = sorted(set([rel] + impacted))
        ext = os.path.splitext(rel)[1].lower()
        checks = ["diagnostics"]
        if ext == ".py":
            checks.append("python targeted tests")
        if rel.startswith("gui/") or ext in {".ts", ".tsx", ".js", ".jsx", ".css"}:
            checks.append("gui build")
        if impacted:
            checks.append("side-effect review")
        risk = "high" if len(impacted) >= 5 else "medium" if impacted else "low"
        return EditPlan(
            target=rel,
            exists=os.path.exists(abs_path),
            language=node.language if node else self._language_from_ext(ext),
            symbols=node.symbols if node else [],
            imports=node.imports if node else [],
            impacted_files=impacted,
            diagnostics_targets=diagnostics,
            recommended_checks=checks,
            risk=risk,
        )

    def _resolve(self, path: str) -> str:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return candidate

    @staticmethod
    def _language_from_ext(ext: str) -> str:
        return {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript-react",
            ".js": "javascript",
            ".jsx": "javascript-react",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(ext, "unknown")
