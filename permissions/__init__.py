"""
NEXUS PERMISSION SYSTEM — 4 Autonomy Modes: Auto-Pilot, By-Pass, Approve, Pre-Authorized.
With backwards compatibility for default, plan, bypass, and auto modes.
"""

import fnmatch
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from utils.singleton import ThreadSafeSingleton


class PermissionMode(Enum):
    DEFAULT = "default"            # Prompt per operation (Old)
    PLAN = "plan"                  # Show plan, ask once (Old)
    BYPASS = "bypass"              # Sovereign mode: auto-approve everything
    AUTO = "auto"                  # ML-based classifier (heuristic) (Old)
    AUTO_PILOT = "auto_pilot"      # Heuristic-based autonomous approval (Default)
    APPROVE = "approve"            # Human-in-the-loop: prompt per operation
    PRE_AUTHORIZED = "pre_authorized" # Restricted: only execute from pre-approved whitelist


class PermissionResult:
    def __init__(self, granted: bool, reason: str = "", prompt: str = ""):
        self.granted = granted
        self.reason = reason
        self.prompt = prompt

    def __str__(self):
        return "GRANTED" if self.granted else f"DENIED: {self.reason}"


class PermissionRule:
    """A single permission rule with wildcard pattern matching."""

    def __init__(
        self, tool_pattern: str, action_pattern: str = "*", granted: bool = True
    ):
        self.tool_pattern = tool_pattern
        self.action_pattern = action_pattern
        self.granted = granted

    def matches(self, tool_name: str, action: str = "") -> bool:
        tool_match = fnmatch.fnmatch(tool_name.lower(), self.tool_pattern.lower())
        action_match = fnmatch.fnmatch(action.lower(), self.action_pattern.lower())
        return tool_match and action_match


class PermissionSystem(ThreadSafeSingleton):
    """
    NEXUS Permission System — Hardened with 4 core autonomy modes and backwards compatibility.
    """

    _initialized = False

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # Default to PermissionMode.DEFAULT; loop.py handles runtime setting to AUTO_PILOT
        self.mode = PermissionMode.DEFAULT
        self._rules: List[PermissionRule] = []
        self._pre_authorized_list: List[str] = [] # Whitelist for 'PRE_AUTHORIZED' mode
        self._setup_defaults()

    def _setup_defaults(self):
        """Default safe permissions."""
        self._rules.append(PermissionRule("glob", "*", True))
        self._rules.append(PermissionRule("grep", "*", True))
        self._rules.append(PermissionRule("web_search", "*", True))
        self._rules.append(PermissionRule("web_fetch", "*", True))
        self._rules.append(PermissionRule("file_edit", "view", True))
        self._rules.append(PermissionRule("todo", "*", True))
        self._rules.append(PermissionRule("rag", "*", True))
        self._rules.append(PermissionRule("lsp", "*", True))

    def set_mode(self, mode: PermissionMode):
        self.mode = mode

    def add_rule(
        self, tool_pattern: str, action_pattern: str = "*", granted: bool = True
    ):
        self._rules.append(PermissionRule(tool_pattern, action_pattern, granted))

    def pre_authorize(self, command: str):
        """Adds a command to the whitelist for PRE_AUTHORIZED mode."""
        self._pre_authorized_list.append(command.strip())

    def check(
        self, tool_name: str, action: str = "", context: Dict[str, Any] = None
    ) -> PermissionResult:
        """Check if an operation is permitted under the current mode."""

        # 1. BYPASS: Total Sovereignty
        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(True, "Bypass mode active.")

        # 2. PRE_AUTHORIZED: Only allow already saved/approved commands
        if self.mode == PermissionMode.PRE_AUTHORIZED:
            clean_action = str(action).strip()
            if clean_action in self._pre_authorized_list:
                return PermissionResult(True, "Command found in pre-authorized whitelist.")
            return PermissionResult(False, f"Command '{clean_action}' not pre-authorized.")

        # 3. AUTO / AUTO_PILOT: Heuristic/Risk-based approval
        if self.mode in (PermissionMode.AUTO, PermissionMode.AUTO_PILOT):
            if tool_name.lower() in {"bash", "shell", "exec", "run"}:
                from sandbox.risk import CommandRiskScorer
                assessment = CommandRiskScorer().assess(action)
                if assessment.blocked:
                    return PermissionResult(False, f"Auto-Pilot blocked: {assessment.summary()}")
            dangerous_patterns = ["DROP TABLE", "DELETE FROM"]
            if any(p.lower() in action.lower() for p in dangerous_patterns):
                return PermissionResult(False, "Auto mode blocked destructive data operation")
            return PermissionResult(True, "Auto-Pilot approved.")

        # Check rules (last matching rule wins) for other modes (DEFAULT/APPROVE, PLAN)
        granted = None
        reason = ""
        for rule in self._rules:
            if rule.matches(tool_name, action):
                granted = rule.granted
                reason = f"Rule: {rule.tool_pattern}/{rule.action_pattern}"

        if granted is not None:
            return PermissionResult(granted, reason)

        # 4. DEFAULT / APPROVE: Human-in-the-loop (Default Prompt)
        if self.mode in (PermissionMode.DEFAULT, PermissionMode.APPROVE):
            return PermissionResult(
                False,
                f"Manual approval required for {tool_name}.",
                f"Execute {tool_name}({action})? [y/N]"
            )

        # 5. PLAN: Plan mode
        if self.mode == PermissionMode.PLAN:
            return PermissionResult(True, "Plan mode - included in plan")

        return PermissionResult(False, "Security configuration error.")

    def get_rules(self) -> List[Dict[str, str]]:
        return [
            {"tool": r.tool_pattern, "action": r.action_pattern, "granted": r.granted}
            for r in self._rules
        ]
