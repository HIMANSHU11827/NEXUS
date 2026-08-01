"""
NEXUS PERMISSION SYSTEM — 4 Autonomy Modes: Auto-Pilot, By-Pass, Approve, Pre-Authorized.
With backwards compatibility for default, plan, bypass, and auto modes.
"""

import fnmatch
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
    def __init__(
        self,
        granted: bool,
        reason: str = "",
        prompt: str = "",
        decision: Optional[Dict[str, Any]] = None,
    ):
        self.granted = granted
        self.reason = reason
        self.prompt = prompt
        self.decision = decision or {}

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
        self._decision_log: List[Dict[str, Any]] = []
        self._decision_log_limit = 200
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

    def _ensure_decision_log(self) -> None:
        if not hasattr(self, "_decision_log"):
            self._decision_log = []
        if not hasattr(self, "_decision_log_limit"):
            self._decision_log_limit = 200

    @staticmethod
    def _safe_action_preview(action: str) -> str:
        preview = str(action or "").replace("\r", " ").replace("\n", " ").strip()
        preview = re.sub(
            r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*=\s*[^\s&;]+",
            lambda match: f"{match.group(1)}=[REDACTED]",
            preview,
        )
        preview = re.sub(
            r"(?i)(authorization:\s*bearer\s+)[^\s&;]+",
            lambda match: f"{match.group(1)}[REDACTED]",
            preview,
        )
        preview = re.sub(r"\b(?:sk-proj-|sk-)[A-Za-z0-9_-]{8,}\b", "[REDACTED]", preview)
        return preview[:240]

    def _result(
        self,
        granted: bool,
        reason: str,
        *,
        tool_name: str,
        action: str,
        prompt: str = "",
        source: str = "",
        rule: Optional[PermissionRule] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PermissionResult:
        self._ensure_decision_log()
        decision = {
            "timestamp": time.time(),
            "mode": self.mode.value,
            "tool": str(tool_name or ""),
            "action_preview": self._safe_action_preview(action),
            "granted": bool(granted),
            "decision": "allow" if granted else "deny",
            "reason": reason,
            "source": source or "permission_system",
        }
        if rule is not None:
            decision["matched_rule"] = {
                "tool": rule.tool_pattern,
                "action": rule.action_pattern,
                "granted": rule.granted,
            }
        if context:
            for key in ("run_id", "turn_id", "session_id", "surface"):
                if key in context:
                    decision[key] = str(context[key])
        self._decision_log.append(decision)
        if len(self._decision_log) > self._decision_log_limit:
            del self._decision_log[: len(self._decision_log) - self._decision_log_limit]
        return PermissionResult(granted, reason, prompt, decision)

    def get_decision_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent permission decisions with scrubbed action previews."""
        self._ensure_decision_log()
        safe_limit = max(1, min(int(limit or 50), self._decision_log_limit))
        return [dict(item) for item in self._decision_log[-safe_limit:]]

    @staticmethod
    def _safety_overlay(tool_name: str, action: str, mode=None) -> Optional[Dict[str, str]]:
        """Consult the persistent Safety settings before legacy mode rules.

        The Safety page owns Permission Mode and Sandbox Mode as first-class,
        workspace-independent settings. This overlay enforces them at the single
        chokepoint used by the agent loop, keeping the three systems separate:
        workspace selection, permission mode, and sandbox mode.

        Returns ``None`` when the overlay has nothing to add (normal rules apply),
        or ``{"decision": ..., "reason": ..., "source": ...}``.
        """
        try:
            from safety.safety_store import get_state, enforce_command
        except Exception:
            return None
        try:
            state = get_state()
            permission = str(state.get("permission_mode") or "automatic")
            sandbox = str(state.get("sandbox_mode") or "workspace")
        except Exception:
            return None

        # 0. Sandbox "no tools" always disables tool execution — a first-class
        # safety gate independent of the permission mode.
        if sandbox == "no_tools":
            return {
                "decision": "deny",
                "reason": "No-tools sandbox mode is active. Tool execution is disabled; Nexus responds with text only.",
                "source": "safety:no_tools",
            }

        if permission == "deny_all":
            return {
                "decision": "deny",
                "reason": "Deny all tools mode is active. Nexus may respond with text only.",
                "source": "safety:deny_all",
            }

        tool = str(tool_name or "").lower()
        is_read = bool(re.match(
            r"^(glob|grep|rg|search|read|view|read_file|get_file|list|ls|tree|todo|rag|lsp|web_search|web_fetch|fetch|describe|status|health|inspect|peek|head|tail)$",
            tool,
        ) or tool.startswith("read_") or tool.endswith("_read"))
        is_shell = tool in {"bash", "shell", "terminal", "exec", "run", "run_command", "command", "powershell", "cmd", "pwsh"}

        def _command_assessment():
            try:
                return enforce_command(str(action or ""), tool=tool)
            except Exception:
                return None

        if permission == "read_only":
            # Safe reads and read-only commands run; everything else is denied.
            if is_read:
                return {
                    "decision": "allow",
                    "reason": "Read-only mode allows safe reads.",
                    "source": "safety:read_only",
                }
            if is_shell:
                assessment = _command_assessment()
                if assessment is not None:
                    if assessment.decision in ("deny", "block"):
                        return {"decision": "deny", "reason": assessment.reason, "source": "safety:read_only"}
                    if assessment.decision == "ask":
                        return {"decision": "ask", "reason": assessment.reason, "source": "mode:manual_approval"}
                    if assessment.decision == "allow":
                        return {"decision": "allow", "reason": "Read-only mode allows this safe command.", "source": "safety:read_only"}
            return {
                "decision": "deny",
                "reason": "Read-only mode denies this action.",
                "source": "safety:read_only",
            }

        if permission == "restricted":
            # Safe reads are permitted; other actions require approval.
            if is_read:
                return {"decision": "allow", "reason": "Restricted mode allows safe reads.", "source": "safety:restricted"}
            return {
                "decision": "ask",
                "reason": "Restricted mode requires approval for this action.",
                "source": "mode:manual_approval",
            }

        # Automatic / ask / trusted / custom modes: blocked command policies are
        # never run. Deny-policy categories are enforced at the chokepoint; ask
        # and allow decisions fall through to the legacy mode handling so the
        # permission mode still controls prompting.
        # Legacy BYPASS ("Total Sovereignty") is the explicit override for the
        # default posture: a user who chose it trusts everything, so policy
        # denials yield back to the legacy mode. Explicit Safety modes above
        # (no_tools / deny_all / read_only / restricted) still win over BYPASS.
        if mode == PermissionMode.BYPASS:
            return None
        if is_shell:
            assessment = _command_assessment()
            if assessment is not None and assessment.decision in ("deny", "block"):
                return {
                    "decision": "deny",
                    "reason": assessment.reason,
                    "source": "safety:command_policy",
                }

        return None

    def check(
        self, tool_name: str, action: str = "", context: Dict[str, Any] = None
    ) -> PermissionResult:
        """Check if an operation is permitted under the current mode."""

        # 0. Persistent Safety overlay (independent of the legacy mode enum).
        overlay = self._safety_overlay(tool_name, action, mode=self.mode)
        if overlay is not None:
            decision = overlay.get("decision")
            if decision == "ask":
                return self._result(
                    False,
                    overlay.get("reason", "Manual approval required."),
                    prompt=f"Execute {tool_name}({action})? [y/N]",
                    tool_name=tool_name,
                    action=action,
                    source="mode:manual_approval",
                    context=context,
                )
            return self._result(
                False,
                overlay.get("reason", "Blocked by safety policy."),
                tool_name=tool_name,
                action=action,
                source=overlay.get("source", "safety"),
                context=context,
            )

        # 1. BYPASS: Total Sovereignty
        if self.mode == PermissionMode.BYPASS:
            return self._result(
                True,
                "Bypass mode active.",
                tool_name=tool_name,
                action=action,
                source="mode:bypass",
                context=context,
            )

        # 2. PRE_AUTHORIZED: Only allow already saved/approved commands
        if self.mode == PermissionMode.PRE_AUTHORIZED:
            clean_action = str(action).strip()
            if clean_action in self._pre_authorized_list:
                return self._result(
                    True,
                    "Command found in pre-authorized whitelist.",
                    tool_name=tool_name,
                    action=action,
                    source="mode:pre_authorized",
                    context=context,
                )
            return self._result(
                False,
                f"Command '{clean_action}' not pre-authorized.",
                tool_name=tool_name,
                action=action,
                source="mode:pre_authorized",
                context=context,
            )

        matching_rules = [
            rule for rule in self._rules
            if rule.matches(tool_name, action)
        ]
        deny_rule = next((rule for rule in matching_rules if not rule.granted), None)
        if deny_rule is not None:
            return self._result(
                False,
                f"Denied by rule: {deny_rule.tool_pattern}/{deny_rule.action_pattern}",
                tool_name=tool_name,
                action=action,
                source="rule:deny",
                rule=deny_rule,
                context=context,
            )
        allow_rule = next((rule for rule in matching_rules if rule.granted), None)

        # 3. AUTO / AUTO_PILOT: Heuristic/Risk-based approval plus explicit policy rules.
        if self.mode in (PermissionMode.AUTO, PermissionMode.AUTO_PILOT):
            if tool_name.lower() in {"bash", "shell", "exec", "run", "run_command", "terminal"}:
                from sandbox.risk import CommandRiskScorer
                assessment = CommandRiskScorer().assess(action)
                if assessment.blocked:
                    return self._result(
                        False,
                        f"Auto-Pilot blocked: {assessment.summary()}",
                        tool_name=tool_name,
                        action=action,
                        source="risk_scorer",
                        context=context,
                    )
            dangerous_patterns = ["DROP TABLE", "DELETE FROM"]
            action_s = str(action or "")
            if any(p.lower() in action_s.lower() for p in dangerous_patterns):
                return self._result(
                    False,
                    "Auto mode blocked destructive data operation",
                    tool_name=tool_name,
                    action=action,
                    source="heuristic:data_destruction",
                    context=context,
                )
            return self._result(
                True,
                "Auto-Pilot approved.",
                tool_name=tool_name,
                action=action,
                source="mode:auto_pilot",
                context=context,
            )

        # Explicit denies win before allows, regardless of append order.
        if allow_rule is not None:
            return self._result(
                True,
                f"Allowed by rule: {allow_rule.tool_pattern}/{allow_rule.action_pattern}",
                tool_name=tool_name,
                action=action,
                source="rule:allow",
                rule=allow_rule,
                context=context,
            )

        # 4. DEFAULT / APPROVE: Human-in-the-loop (Default Prompt)
        if self.mode in (PermissionMode.DEFAULT, PermissionMode.APPROVE):
            return self._result(
                False,
                f"Manual approval required for {tool_name}.",
                prompt=f"Execute {tool_name}({action})? [y/N]",
                tool_name=tool_name,
                action=action,
                source="mode:manual_approval",
                context=context,
            )

        # 5. PLAN: Plan mode
        if self.mode == PermissionMode.PLAN:
            return self._result(
                True,
                "Plan mode - included in plan",
                tool_name=tool_name,
                action=action,
                source="mode:plan",
                context=context,
            )

        return self._result(
            False,
            "Security configuration error.",
            tool_name=tool_name,
            action=action,
            source="configuration_error",
            context=context,
        )

    def get_rules(self) -> List[Dict[str, str]]:
        return [
            {"tool": r.tool_pattern, "action": r.action_pattern, "granted": r.granted}
            for r in self._rules
        ]
