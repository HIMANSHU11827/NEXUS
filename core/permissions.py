"""
NEXUS PERMISSION SYSTEM — Claude Code permission modes adapted for Python.
Supports: default, plan, bypass, auto modes with wildcard pattern matching.
"""

import re
import fnmatch
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from utils.singleton import ThreadSafeSingleton


class PermissionMode(Enum):
    DEFAULT = "default"  # Prompt per operation
    PLAN = "plan"  # Show plan, ask once
    BYPASS = "bypass"  # Auto-approve everything
    AUTO = "auto"  # ML-based classifier (heuristic)


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
    NEXUS Permission System — Controls tool access with configurable modes.
    """

    _initialized = False

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.mode = PermissionMode.DEFAULT
        self._rules: List[PermissionRule] = []
        self._setup_defaults()

    def _setup_defaults(self):
        """Default safe permissions."""
        # Always allow read-only operations
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

    def check(
        self, tool_name: str, action: str = "", context: Dict[str, Any] = None
    ) -> PermissionResult:
        """Check if an operation is permitted."""

        # Bypass mode: auto-approve
        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(True, "Bypass mode")

        # Auto mode: heuristic approval
        if self.mode == PermissionMode.AUTO:
            if tool_name.lower() in {"bash", "shell", "exec", "run"}:
                from core.autonomy.risk import CommandRiskScorer

                assessment = CommandRiskScorer().assess(action)
                if assessment.blocked:
                    return PermissionResult(False, f"Auto mode blocked {assessment.summary()}")
            dangerous_patterns = ["DROP TABLE", "DELETE FROM"]
            if any(p.lower() in action.lower() for p in dangerous_patterns):
                return PermissionResult(False, "Auto mode blocked destructive data operation")
            return PermissionResult(True, "Auto mode approved")

        # Check rules (last matching rule wins)
        granted = None
        reason = ""
        for rule in self._rules:
            if rule.matches(tool_name, action):
                granted = rule.granted
                reason = f"Rule: {rule.tool_pattern}/{rule.action_pattern}"

        if granted is not None:
            return PermissionResult(granted, reason)

        # Default mode: require explicit approval
        if self.mode == PermissionMode.DEFAULT:
            return PermissionResult(
                False,
                f"Permission required for {tool_name}/{action}",
                f"Allow {tool_name}({action})? [y/N]",
            )

        # Plan mode: approve but note it
        if self.mode == PermissionMode.PLAN:
            return PermissionResult(True, "Plan mode - included in plan")

        return PermissionResult(False, "No matching rule")

    def get_rules(self) -> List[Dict[str, str]]:
        return [
            {"tool": r.tool_pattern, "action": r.action_pattern, "granted": r.granted}
            for r in self._rules
        ]
