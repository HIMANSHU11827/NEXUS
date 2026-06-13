"""Predict cross-file side effects from planned edits."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Dict, List

from code_intel.repo_map import RepoMapBuilder


@dataclass
class SideEffectReport:
    target_file: str
    impacted_files: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    risk: str = "low"


class SideEffectAnalyzer:
    """Uses the repo map imports/symbols to estimate edit blast radius."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.repo_map = RepoMapBuilder(root_dir).build()

    def analyze(self, target_file: str) -> SideEffectReport:
        normalized = target_file.replace("\\", "/").strip("/")
        module_hint = normalized.rsplit(".", 1)[0].replace("/", ".")
        basename = os.path.basename(normalized).rsplit(".", 1)[0]
        impacted: List[str] = []
        reasons: List[str] = []
        for node in self.repo_map.files:
            if node.path == normalized:
                continue
            imports = " ".join(node.imports)
            if module_hint in imports or basename in imports:
                impacted.append(node.path)
                reasons.append(f"{node.path} imports {module_hint or basename}")
        risk = "low"
        if len(impacted) >= 8:
            risk = "high"
        elif len(impacted) >= 3:
            risk = "medium"
        return SideEffectReport(normalized, impacted, reasons, risk)
