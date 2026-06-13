import yaml
import os
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

class NexusLawKernel:
    """
    Policy audit engine.
    Enforces project security and data-governance rules on tool calls.
    """
    
    def __init__(self, laws_path: str = None):
        if laws_path is None:
            laws_path = str(Path(__file__).parent.parent.parent / "core" / "safety" / "sovereign_laws.yaml")
        
        self.laws_path = laws_path
        self.laws = self._load_laws()

    def _load_laws(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.laws_path):
            # Default internal laws if file is missing
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

    def audit(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Audits a tool call against the law kernel."""
        param_str = str(params).lower()
        
        for law in self.laws:
            if re.search(law["pattern"], param_str, re.IGNORECASE):
                return {
                    "granted": law["action"] != "BLOCK",
                    "reason": law["reason"],
                    "law_name": law["name"],
                    "action_taken": law["action"]
                }
        
        return {"granted": True, "reason": "No law violations detected.", "action_taken": "ALLOW"}
