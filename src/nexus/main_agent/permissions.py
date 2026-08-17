"""V5Permissions - permission modes and checks for the V5 loop.

Four main modes: BYPASS, AUTO_PILOT, APPROVE, PRE_AUTHORIZED.
Wraps permissions.PermissionSystem + ApprovalBroker; V5 with
loop.py _init_permissions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ALLOWED_MODES = frozenset({"BYPASS", "AUTO_PILOT", "APPROVE", "PRE_AUTHORIZED"})


class V5Permissions:
    """Mixin giving the V5 loop ownership of permission handling.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.runtime`` - object with ``.permission_policy`` (enum with
      ``.value`` in auto/ai_decide/ask_all/checklist), ``.checklist``,
      settable ``.permissions`` and ``.permission_mode_value``; may be None
      in exotic cases, everything is guarded.
    - ``self.kernel`` - optional kernel exposing ``_get_or_init(key, factory)``;
      used only to recover the permission system when the runtime lacks one.
    - ``self.logger`` - logger exposing ``.info``/``.debug``/``.warning``.
    - ``self.session_id`` - session id forwarded to approval requests.
    """

    def _init_permissions(self):
        """Initialize permission system from V1 and sync the active policy."""
        try:
            from security.permissions import PermissionMode
            from security.permissions import PermissionSystem
            system = PermissionSystem()
            policy = getattr(getattr(self, "runtime", None), "permission_policy", None)
            policy_value = str(getattr(policy, "value", None) or policy or "").lower()
            if policy_value == "auto":
                system.set_mode(PermissionMode.BYPASS)
            elif policy_value == "ai_decide":
                system.set_mode(PermissionMode.AUTO_PILOT)
            elif policy_value == "ask_all":
                system.set_mode(PermissionMode.APPROVE)
            elif policy_value == "checklist":
                system.set_mode(PermissionMode.PRE_AUTHORIZED)
                system._pre_authorized_list = list(
                    getattr(getattr(self, "runtime", None), "checklist", None) or []
                )
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                runtime.permissions = system
                runtime.permission_mode_value = getattr(
                    getattr(system, "mode", None), "value", None
                )
            self.logger.info(
                "V5 loop permissions initialized (policy=%s)", policy_value
            )
        except Exception as e:
            self.logger.warning(f"Could not initialize permissions: {e}")

    def _permission_system(self):
        """Return the active PermissionSystem or None; never raises."""
        try:
            runtime = getattr(self, "runtime", None)
            if runtime is None:
                return None
            system = getattr(runtime, "permissions", None)
            if system is not None:
                return system
            kernel = getattr(self, "kernel", None)
            factory = getattr(kernel, "_get_or_init", None)
            if factory is None:
                return None
            from security.permissions import PermissionSystem
            system = factory("permissions", PermissionSystem)
            if system is not None:
                runtime.permissions = system
            return system
        except Exception:
            return None

    def _permission_mode(self) -> str:
        """Return the active permission mode as a string; "" on failure."""
        try:
            system = self._permission_system()
            if system is not None:
                mode = getattr(system, "mode", None)
                value = getattr(mode, "value", None)
                if value is not None:
                    return str(value)
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                recorded = getattr(runtime, "permission_mode_value", None)
                if recorded is not None:
                    return str(recorded)
            return ""
        except Exception:
            return ""

    def _set_permission_mode(self, mode: Any) -> bool:
        """Set the permission mode from a PermissionMode member or a string.

        Only the four main modes are accepted: BYPASS, AUTO_PILOT, APPROVE,
        PRE_AUTHORIZED (case-insensitive when given as a string).
        """
        try:
            if isinstance(mode, str):
                name = str(mode).strip().upper()
                if name not in _ALLOWED_MODES:
                    return False
                from security.permissions import PermissionMode
                resolved = PermissionMode[name]
            else:
                resolved = mode
                if getattr(resolved, "name", None) not in _ALLOWED_MODES:
                    return False
            system = self._permission_system()
            if system is None:
                return False
            system.set_mode(resolved)
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                runtime.permission_mode_value = getattr(resolved, "value", None)
            return True
        except Exception:
            return False

    def _check_permission(
        self, tool_name: str, action: str, context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Check one operation against the active mode; None on failure."""
        try:
            system = self._permission_system()
            if system is None:
                return None
            return system.check(tool_name, action, context=context or {})
        except Exception:
            return None

    def _add_permission_rule(self, tool_name: str, action: str = "*", granted: bool = True) -> bool:
        """Add an allow/deny rule to the permission system."""
        try:
            system = self._permission_system()
            if system is None:
                return False
            system.add_rule(tool_name, action, granted)
            return True
        except Exception:
            return False

    def _pre_authorize(self, command: str) -> bool:
        """Add a command to the pre-authorized whitelist."""
        try:
            system = self._permission_system()
            if system is None:
                return False
            system.pre_authorize(command)
            return True
        except Exception:
            return False

    def _permission_rules(self) -> List[Dict[str, str]]:
        """Return the current permission rules or []."""
        try:
            system = self._permission_system()
            if system is None:
                return []
            return list(system.get_rules() or [])
        except Exception:
            return []

    def _decision_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent permission decisions or []."""
        try:
            system = self._permission_system()
            if system is None:
                return []
            return list(system.get_decision_log(limit) or [])
        except Exception:
            return []

    def _approval_broker(self):
        """Return the process-wide ApprovalBroker singleton; None on failure."""
        try:
            from security.permissions.approval_broker import get_approval_broker
            broker = get_approval_broker()
            if broker is not None:
                return broker
            from security.permissions.approval_broker import ApprovalBroker
            broker = ApprovalBroker()
            setattr(self, "_v5_approval_broker", broker)
            return broker
        except Exception:
            return None

    def _open_approval(
        self, tool_name: str, action: str, session_id: str = "", timeout: float = 300.0
    ) -> Optional[str]:
        """Open a human approval request; returns the request id or None."""
        try:
            broker = self._approval_broker()
            if broker is None:
                return None
            request = broker.open(
                session_id=session_id,
                tool_name=tool_name,
                action=action,
                timeout_s=timeout,
            )
            return getattr(request, "request_id", None)
        except Exception:
            return None

    def _resolve_approval(self, request_id: str, decision: Any) -> bool:
        """Record a human decision for a pending approval request."""
        try:
            broker = self._approval_broker()
            if broker is None:
                return False
            return bool(broker.resolve(request_id, decision))
        except Exception:
            return False

    def _pending_approvals(self, session_id: str = "") -> list:
        """Return pending approval requests for a session or []."""
        try:
            broker = self._approval_broker()
            if broker is None:
                return []
            return list(broker.pending(session_id) or [])
        except Exception:
            return []

    def _permission_stats(self) -> Dict[str, Any]:
        """Return a summary of the current permission state."""
        try:
            return {
                "mode": self._permission_mode(),
                "rules": len(self._permission_rules()),
                "decisions": len(self._decision_log(500)),
            }
        except Exception:
            return {"mode": "", "rules": 0, "decisions": 0}
