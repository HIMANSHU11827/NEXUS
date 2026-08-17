"""
NEXUS PERMISSION SYSTEM — 4 Autonomy Modes: Auto-Pilot, By-Pass, Approve, Pre-Authorized.
With backwards compatibility for default, plan, bypass, and auto modes.
"""

import fnmatch
import json
import os
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.singleton import ThreadSafeSingleton

# JSONL ledger under the user's NEXUS home: one line per decision, so the
# in-memory ring (capped at 200) can be re-hydrated on the next process start
# and the API decision endpoint sees prior sessions too.  The path is a module
# constant so tests can redirect it; every write/read degrades to in-memory-only
# on IO failure.
_DECISION_LOG_DIR = os.path.join(os.path.expanduser("~"), ".nexus", "permissions")
DECISIONS_LOG_FILE = os.path.join(_DECISION_LOG_DIR, "decisions.jsonl")

# Per-agent allow/deny rules live in the NEXUS config dir.  Absent file == empty
# rules; a malformed file degrades to empty rules, never an exception.
_NEXUS_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configure"
)
DEFAULT_AGENT_RULES_FILE = os.path.join(_NEXUS_CONFIG_DIR, "permission_agents.yml")


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
        # Per-agent allow/deny rules, keyed by agent_id. Loaded once from
        # config/permission_agents.yml (empty when absent). Only consulted when
        # check() is called with an explicit agent_id.
        self.agent_rules: Dict[str, Dict[str, Any]] = {}
        self._setup_defaults()
        self.agent_rules = self._load_agent_rules()
        self._load_decision_history()

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
        # Skill permissions - all skill operations allowed by default
        self._rules.append(PermissionRule("skill_view", "*", True))
        self._rules.append(PermissionRule("skills_list", "*", True))
        self._rules.append(PermissionRule("skill_manage", "view", True))
        self._rules.append(PermissionRule("skill_manage", "list", True))
        self._rules.append(PermissionRule("skill_manage", "read", True))
        self._rules.append(PermissionRule("skill_execute", "*", True))
        # Skill mutations require explicit approval in restrictive modes
        self._rules.append(PermissionRule("skill_manage", "write_file", True))
        self._rules.append(PermissionRule("skill_manage", "delete", True))
        self._rules.append(PermissionRule("skill_manage", "create", True))

    # ── JSONL decision ledger ──────────────────────────────────────────────
    def _load_decision_history(self) -> None:
        """Rehydrate the in-memory ring from the JSONL ledger, best-effort.

        Prior-session decisions are loaded first so they trail at the front of
        the ring and new decisions are appended after them. Any IO or parse
        failure degrades to an empty log (in-memory-only), never an exception.
        """
        try:
            path = DECISIONS_LOG_FILE
            if not os.path.isfile(path):
                return
            loaded: List[Dict[str, Any]] = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(entry, dict):
                        loaded.append(entry)
            if loaded:
                self._decision_log = loaded
                if len(self._decision_log) > self._decision_log_limit:
                    del self._decision_log[
                        : len(self._decision_log) - self._decision_log_limit
                    ]
        except Exception:
            self._decision_log = []

    def _persist_decision(self, decision: Dict[str, Any]) -> None:
        """Append one decision to the JSONL ledger; never raises on IO errors.

        A concurrent append failure or an unwritable home must not break the
        permission decision itself, so the ledger degrades to in-memory-only.
        """
        try:
            path = DECISIONS_LOG_FILE
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
            line = json.dumps(decision, ensure_ascii=False, default=str)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    # ── Per-agent rule overlay ─────────────────────────────────────────────
    def _default_agent_rules_path(self) -> str:
        return DEFAULT_AGENT_RULES_FILE

    def _load_agent_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load per-agent allow/deny rules from config/permission_agents.yml.

        Expected shape (``agents`` key is optional):
          agents:
            name:
              deny: ["bash", "deleting"]
              allow: ["reading", "grep"]
        Any missing or malformed file yields empty rules; never raises.
        """
        rules: Dict[str, Dict[str, Any]] = {}
        try:
            from yaml import safe_load
        except Exception:
            return rules
        try:
            path = self._default_agent_rules_path()
            if not path or not os.path.isfile(path):
                return rules
            with open(path, "r", encoding="utf-8") as fh:
                data = safe_load(fh) or {}
            agents = data.get("agents", data) if isinstance(data, dict) else {}
            for agent_id, spec in (agents or {}).items():
                if isinstance(spec, dict):
                    rules[str(agent_id)] = spec
        except Exception:
            rules = {}
        return rules

    def reload_agent_rules(self) -> None:
        """Re-read config/permission_agents.yml into ``agent_rules``."""
        try:
            self.agent_rules = self._load_agent_rules()
        except Exception:
            self.agent_rules = {}

    def get_agent_rules(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.agent_rules or {})

    @staticmethod
    def _agent_entry_matches(entry: Any, tool_name: str, action: str) -> bool:
        """Match one per-agent rule entry against a tool call.

        Accepts a bare pattern string (``"bash"`` or ``"deny:rm *"``) or a
        dict ``{"tool": ..., "action": ...}``. Patterns use glob wildcards and
        are matched case-insensitively against the tool name.
        """
        try:
            tool = str(tool_name or "").lower()
            act = str(action or "")
            if isinstance(entry, str):
                text = str(entry).strip()
                if not text:
                    return False
                # "tool:action" form lets one entry pin both dimensions.
                if ":" in text and not text.startswith(("C:/", "C:\\", "/")):
                    tool_part, _, action_part = text.partition(":")
                    return (
                        fnmatch.fnmatch(tool, tool_part.strip().lower())
                        and fnmatch.fnmatch(act.lower(), action_part.strip().lower())
                    )
                if "*" in text:
                    return fnmatch.fnmatch(tool, text.lower())
                return tool == text.lower()
            if isinstance(entry, dict):
                tool_part = str(entry.get("tool") or "").strip()
                action_part = str(entry.get("action") or "*").strip() or "*"
                if not tool_part:
                    return False
                return fnmatch.fnmatch(tool, tool_part.lower()) and fnmatch.fnmatch(
                    act.lower(), action_part.lower()
                )
        except Exception:
            return False
        return False

    def _agent_deny_reason(self, agent_id: str, tool_name: str, action: str) -> Optional[str]:
        """Return a per-agent deny reason, or None when the agent may proceed.

        A matching ``deny`` entry wins over the global allow list — an agent
        that is barred from a tool stays barred no matter what the system-wide
        rules permit. ``allow`` entries are loaded and exposed via
        ``get_agent_rules()`` for per-agent capability introspection, but never
        auto-grant what a global rule or mode denies.
        """
        try:
            spec = self.agent_rules.get(str(agent_id))
            if not isinstance(spec, dict):
                return None
            for entry in spec.get("deny") or []:
                if self._agent_entry_matches(entry, tool_name, action):
                    return f"Agent rule denies {tool_name} for {agent_id}."
        except Exception:
            return None
        return None

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
            for key in ("run_id", "turn_id", "session_id", "surface", "agent_id"):
                if key in context:
                    decision[key] = str(context[key])
        self._decision_log.append(decision)
        if len(self._decision_log) > self._decision_log_limit:
            del self._decision_log[: len(self._decision_log) - self._decision_log_limit]
        # Mirror every decision to the JSONL ledger (timestamp, provider/surface
        # via context, action preview, grant, matched rule). IO failures degrade
        # silently to in-memory-only.
        self._persist_decision(decision)
        return PermissionResult(granted, reason, prompt, decision)

    def get_decision_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent permission decisions with scrubbed action previews."""
        self._ensure_decision_log()
        safe_limit = max(1, min(int(limit or 50), self._decision_log_limit))
        return [dict(item) for item in self._decision_log[-safe_limit:]]

    def record_approval(
        self,
        tool_name: str,
        action: str,
        *,
        granted: bool,
        session_id: str = "",
    ) -> None:
        """Record a human approval/denial verdict in the decision ledger.

        The broker path is intentionally outside ``check()`` (a human answer,
        not a policy evaluation), so ask-mode verdicts are logged here to keep
        the JSONL ledger a complete audit of "decision then outcome". Never
        raises; a ledger failure degrades to in-memory-only.
        """
        try:
            self._result(
                bool(granted),
                "Approved by human" if granted else "Denied by human",
                tool_name=tool_name,
                action=action,
                source="mode:human_approval",
                context={"session_id": str(session_id)} if session_id else None,
            )
        except Exception:
            pass

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
        self,
        tool_name: str,
        action: str = "",
        context: Dict[str, Any] = None,
        agent_id: Optional[str] = None,
    ) -> PermissionResult:
        """Check if an operation is permitted under the current mode.

        ``agent_id`` is optional per-agent scoping: when provided, a matching
        per-agent ``deny`` entry (config/permission_agents.yml) denies the tool
        regardless of the global rules below. Behavior is unchanged when
        ``agent_id`` is None.
        """

        # 0a. Per-agent overlay: an explicit per-agent deny wins over every
        # global allow and even the safety overlay, so an agent barred from a
        # tool can never smuggle it through a shared allow-list rule.
        if agent_id:
            agent_reason = self._agent_deny_reason(agent_id, tool_name, action)
            if agent_reason is not None:
                agent_context = dict(context or {})
                agent_context.setdefault("agent_id", str(agent_id))
                return self._result(
                    False,
                    agent_reason,
                    tool_name=tool_name,
                    action=action,
                    source="agent:deny",
                    context=agent_context,
                )

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
