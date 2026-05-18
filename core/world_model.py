"""Action impact simulation for autonomous planning.

This is not a fantasy "world simulator". It is a deterministic planning aid:
given a tool action and parameters, it predicts likely filesystem/process risk,
reversibility, and recommended safeguards before execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Any, Dict, List

from core.autonomy.risk import CommandRiskScorer


@dataclass(frozen=True)
class SimulationResult:
    action: str
    target: str
    risk_level: str
    reversible: bool
    predicted_effects: List[str] = field(default_factory=list)
    safeguards: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        effects = "; ".join(self.predicted_effects) or "no material side effects predicted"
        safeguards = "; ".join(self.safeguards) or "standard execution"
        return (
            f"[WORLD_MODEL] action={self.action} target={self.target} "
            f"risk={self.risk_level} reversible={self.reversible} "
            f"effects={effects} safeguards={safeguards}"
        )


class WorldModel:
    """Cheap action simulator for planning and logs."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.risk = CommandRiskScorer()

    def simulate(self, action: str, params: Dict[str, Any] | str) -> SimulationResult:
        if isinstance(params, str):
            target = params
            param_map: Dict[str, Any] = {"raw": params}
        else:
            param_map = params
            target = str(params.get("path") or params.get("command") or params.get("cmd") or params)

        action_l = action.lower()
        effects: List[str] = []
        safeguards: List[str] = []
        risk_level = "low"
        reversible = True

        if action_l in {"bash", "shell", "exec", "run"}:
            command = str(param_map.get("command") or param_map.get("cmd") or target)
            assessment = self.risk.assess(command)
            risk_level = assessment.level
            effects.extend(assessment.reasons)
            reversible = assessment.score < 45
            if assessment.score >= 25:
                safeguards.append("capture stdout/stderr and timeout")
            if assessment.score >= 45:
                safeguards.append("snapshot affected paths before execution")
            if assessment.blocked:
                safeguards.append("block unless NEXUS_ALLOW_DANGEROUS_SHELL=true")
        elif action_l == "file_edit":
            command = str(param_map.get("command") or "")
            path = str(param_map.get("path") or "")
            effects.append(f"file operation: {command or 'unknown'}")
            if command in {"delete", "str_replace", "insert", "create"}:
                safeguards.append("keep edit history / backup")
            if command == "delete":
                risk_level = "high"
                reversible = False
            elif command in {"str_replace", "insert"}:
                risk_level = "medium"
            if path and self._escapes_root(path):
                risk_level = "critical"
                reversible = False
                effects.append("path escapes project root")
                safeguards.append("block path traversal")
        else:
            effects.append("tool side effects unknown")
            safeguards.append("log action and result")

        return SimulationResult(action, target, risk_level, reversible, effects, safeguards)

    def _escapes_root(self, path: str) -> bool:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        try:
            return os.path.commonpath([self.root, candidate]) != self.root
        except ValueError:
            return True
