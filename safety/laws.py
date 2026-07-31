import os
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml


class NexusLawKernel:
    """
    Policy audit engine.
    Enforces project security and data-governance rules on tool calls.
    """

    def __init__(self, laws_path: str = None):
        if laws_path is None:
            laws_path = str(Path(__file__).parent / "sovereign_laws.yaml")
        self.laws_path = laws_path
        self.laws = self._load_laws()
        self._compiled = self._compile_laws(self.laws)

    def _load_laws(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(self.laws_path):
            return [
                {
                    "name": "data_sovereignty",
                    "pattern": r"rm -rf /|del /s /q",
                    "action": "BLOCK",
                    "reason": "Destructive system-wide deletion is prohibited."
                },
                {
                    "name": "credential_protection",
                    "pattern": r"env|printenv|set",
                    "action": "AUDIT",
                    "reason": "Environment variable access requires auditing."
                }
            ]
        with open(self.laws_path, "r") as f:
            return yaml.safe_load(f).get("laws", [])

    def _compile_laws(self, laws: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Precompile each law's regex once; skip malformed laws instead of crashing
        mid-audit."""
        compiled: List[Dict[str, Any]] = []
        for law in laws or []:
            if not isinstance(law, dict):
                continue
            pat = law.get("pattern")
            if not pat:
                continue
            try:
                regex = re.compile(pat, re.IGNORECASE)
            except re.error:
                continue
            entry = dict(law)
            entry["_re"] = regex
            compiled.append(entry)
        return compiled

    def audit(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Audits a tool call against the law kernel.

        Scans ALL laws and lets the most severe action win (BLOCK overrides AUDIT/
        ALLOW) so a destructive command is never approved just because an earlier,
        less severe AUDIT rule also matched.
        """
        param_str = str(params).lower()

        matched = None
        blocked = None
        for law in self._compiled:
            regex = law.get("_re")
            if regex is None or not regex.search(param_str):
                continue
            action_taken = law.get("action", "ALLOW")
            if action_taken == "BLOCK":
                blocked = {
                    "granted": False,
                    "reason": law.get("reason", "Blocked by law"),
                    "law_name": law.get("name", "unknown"),
                    "action_taken": "BLOCK",
                }
                break
            if matched is None:
                matched = {
                    "granted": action_taken != "BLOCK",
                    "reason": law.get("reason", ""),
                    "law_name": law.get("name", "unknown"),
                    "action_taken": action_taken,
                }

        if blocked is not None:
            return blocked
        if matched is not None:
            return matched
        return {"granted": True, "reason": "No law violations detected.", "action_taken": "ALLOW"}
