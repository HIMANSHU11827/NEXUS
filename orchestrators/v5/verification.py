"""V5 tool-execution evidence verification mixin.

Ports the V1 unified-loop verification section (``orchestrators/loop.py`` —
``_observations_contain_failure``, ``_deterministic_evidence_summary`` and
``_is_raw_tool_result_dump``) so the V5 loop can never claim success when a
real tool execution failed. Every method here is provider-independent and
grounded only in real tool evidence; ``_verify_result`` rewrites the PAORR
result dict so downstream stages see the truth before building any summary.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_FAILURE_KEYWORDS: tuple = (
    "error:",
    "exception:",
    "traceback:",
    "traceback (most recent call last)",
    "command exited with code",
    "command not found",
    "is not recognized",
    "failed:",
)
_EXIT_CODE_PATTERN = re.compile(r"^\[exit_code\]\s*:?\s*[1-9]\d*")
_OUTPUT_LIMIT = 2000
_ANOMALY_LIMIT = 5
_EVIDENCE_LIMIT = 1500
_REPAIR_MAX_ATTEMPTS = 2


class V5Verifier:
    """Mixin verifying tool-execution evidence inside V5 PAORR results."""

    @staticmethod
    def _action_get(action: Any, key: str, default: Any = None) -> Any:
        """Read a field from a dict action or an object action (ActionResult)."""
        if isinstance(action, dict):
            return action.get(key, default)
        return getattr(action, key, default)

    @staticmethod
    def _action_set(action: Any, key: str, value: Any) -> None:
        """Write a field onto a dict action or an object action."""
        if isinstance(action, dict):
            action[key] = value
        else:
            try:
                setattr(action, key, value)
            except Exception:
                pass

    @staticmethod
    def _is_failure_text(text: str) -> bool:
        """Return True when *text* carries concrete failure evidence."""
        if not text:
            return False
        for line in str(text).splitlines():
            line_low = line.lower()
            if _EXIT_CODE_PATTERN.match(line_low):
                return True
            if any(keyword in line_low for keyword in _FAILURE_KEYWORDS):
                return True
        return False

    @staticmethod
    def _action_evidence(action: Any) -> str:
        """Shortest truthful description of an action: description/error/output."""
        for key in ("description", "error", "output"):
            value = str(V5Verifier._action_get(action, key) or "").strip()
            if value:
                return value
        return "unidentified action"

    @staticmethod
    def _action_succeeded(action: Any) -> bool:
        """Action success, preferring the verifier's ``verified`` flag."""
        verified = V5Verifier._action_get(action, "verified")
        success = V5Verifier._action_get(action, "success", True)
        return bool(verified if verified is not None else success)

    async def _verify_result(
        self, result: Dict[str, Any], perceived: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Scan every action for failure evidence and rewrite *result* truthfully.

        Failed actions get ``verified=False``; any failure flips
        ``result["success"]`` to False and is recorded in
        ``result["observation"]["anomalies"]``. The fresh ``verification`` dict
        is always stored and the same dict is returned.
        """
        raw_actions = result.get("actions") if isinstance(result, dict) else None
        actions: List[Any] = list(raw_actions or [])
        failed: List[Any] = []
        for action in actions:
            failed_now = (
                not self._action_get(action, "success", True)
                or self._is_failure_text(str(self._action_get(action, "error") or ""))
                or self._is_failure_text(str(self._action_get(action, "output") or ""))
            )
            self._action_set(action, "verified", not failed_now)
            if failed_now:
                failed.append(action)

        # A plan is not verified merely because the subset that ran
        # succeeded.  Dependency failures and scheduler stalls can leave
        # planned steps without an action record; expose that as concrete
        # verification evidence so repair/replan can act on it.
        plan = result.get("plan") if isinstance(result, dict) else None
        planned_steps = plan.get("steps") if isinstance(plan, dict) else getattr(plan, "steps", None)
        planned_count = len(planned_steps) if isinstance(planned_steps, (list, tuple)) else 0
        missing_count = max(0, planned_count - len(actions))
        if missing_count:
            failed.append({
                "success": False,
                "description": f"{missing_count} planned step(s) produced no action result",
                "error": "execution did not produce evidence for every planned step",
            })

        result["verification"] = {
            "success": not failed,
            "verified_actions": max(0, len(actions) - min(len(actions), len(failed))),
            "total_actions": max(len(actions), planned_count),
            "failed_actions": len(failed),
            "anomalies": [
                self._action_evidence(action)[:_ANOMALY_LIMIT * 100]
                for action in failed[: _ANOMALY_LIMIT]
            ],
            "evidence_ok": not failed,
        }

        if failed:
            result["success"] = False
            observation = result.get("observation")
            if not isinstance(observation, dict):
                observation = {}
                result["observation"] = observation
            anomalies = observation.get("anomalies")
            if not isinstance(anomalies, list):
                anomalies = []
                observation["anomalies"] = anomalies
            anomalies.append(
                f"verification failed: {len(failed)} action(s) show failure evidence"
            )
        return result

    def _evidence_summary(self, result: Dict[str, Any]) -> str:
        """Grounded deterministic summary built only from real tool evidence."""
        verification = result.get("verification") if isinstance(result, dict) else None
        verification_failed = isinstance(verification, dict) and not verification.get(
            "success", True
        )
        if not isinstance(result, dict) or result.get("success") is False or verification_failed:
            return self._failure_summary(result if isinstance(result, dict) else {})

        actions: List[Any] = [
            action
            for action in (result.get("actions") or [])
            if self._action_succeeded(action)
        ]
        outputs = [
            str(self._action_get(action, "output") or "").strip()[:_OUTPUT_LIMIT]
            for action in actions
            if str(self._action_get(action, "output") or "").strip()
        ]
        if not outputs:
            return "Work completed and verified."
        return "Work completed and verified.\n\n" + "\n".join(
            f"- {item}" for item in outputs[:_ANOMALY_LIMIT]
        )

    def _failure_summary(self, result: Dict[str, Any]) -> str:
        """Failure summary listing real failed-action evidence (max 5)."""
        failed_actions = [
            action
            for action in (result.get("actions") or [])
            if not self._action_succeeded(action)
        ]
        evidence = [
            self._action_evidence(action)[:_OUTPUT_LIMIT]
            for action in failed_actions[:_ANOMALY_LIMIT]
        ]
        if not evidence:
            return "Some steps did not complete. Evidence: no detailed evidence available."
        return "Some steps did not complete. Evidence: " + "\n- ".join(evidence)

    # ────────────────────────────────────────────────────────────────────────
    # REPAIR FEEDBACK (roadmap item 3: bounded self-repair)
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _evidence_value(value: Any) -> str:
        """Plain-text rendering of one evidence item (dict-safe)."""
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("error", "message", "detail"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return str(value).strip()
        if isinstance(value, (list, tuple, set)):
            return ""
        return str(value).strip()

    def _failure_evidence(self, result: Dict[str, Any]) -> str:
        """Compact (<=1500 chars) plain-text digest of failure evidence.

        Collects the verification verdict, top-level errors, observation
        anomalies and failed actions with their error messages. Returns ""
        when nothing failed; never raises.
        """
        try:
            if not isinstance(result, dict):
                return ""
            pieces: List[str] = []

            verification = result.get("verification")
            if isinstance(verification, dict) and not verification.get("success", True):
                pieces.append(
                    "verification verdict: failed "
                    f"({verification.get('failed_actions', 0)} failed action(s))"
                )
                anomalies = verification.get("anomalies")
                if isinstance(anomalies, list):
                    for anomaly in anomalies:
                        text = self._evidence_value(anomaly)
                        if text:
                            pieces.append(f"- {text}")

            for key in ("error", "errors", "exception"):
                value = result.get(key)
                if isinstance(value, list):
                    for item in value:
                        text = self._evidence_value(item)
                        if text:
                            pieces.append(f"- {text}")
                else:
                    text = self._evidence_value(value)
                    if text:
                        pieces.append(f"- {text}")

            observation = result.get("observation")
            if isinstance(observation, dict):
                anomalies = observation.get("anomalies")
                if isinstance(anomalies, list):
                    for anomaly in anomalies:
                        text = self._evidence_value(anomaly)
                        if text:
                            pieces.append(f"- {text}")

            raw_actions = result.get("actions") or []
            if not isinstance(raw_actions, list):
                try:
                    raw_actions = list(raw_actions)
                except Exception:
                    raw_actions = []
            for action in raw_actions:
                if self._action_succeeded(action):
                    continue
                description = str(
                    self._action_get(action, "description") or ""
                ).strip()
                error = str(self._action_get(action, "error") or "").strip()
                tool = str(self._action_get(action, "tool") or "").strip()
                label = description or (f"tool {tool}" if tool else "action")
                if error:
                    pieces.append(f"- failed action ({label}): {error}")
                else:
                    pieces.append(f"- failed action ({label})")

            if not pieces:
                return ""
            digest = "\n".join(pieces)
            if len(digest) > _EVIDENCE_LIMIT:
                digest = digest[:_EVIDENCE_LIMIT].rstrip() + "…"
            return digest
        except Exception:
            return ""

    def _repair_instruction(
        self, result: Dict[str, Any], perceived: Optional[Any] = None
    ) -> str:
        """Corrective prompt paragraph for the planner; "" when nothing failed.

        Routes the failure evidence to the model in-band so the corrective
        plan fixes the observed root causes instead of repeating the plan.
        """
        evidence = self._failure_evidence(result)
        if not evidence:
            return ""
        return (
            "\n\nPrevious attempt failed. Fix the root causes below, "
            "then complete the task.\nFailure evidence: " + evidence + "\n"
        )

    @staticmethod
    def _repair_budget(attempt: int, max_attempts: int = _REPAIR_MAX_ATTEMPTS) -> bool:
        """True while the 1-based *attempt* is inside the repair budget."""
        try:
            return 1 <= int(attempt) <= max_attempts
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_raw_tool_result_dump(text: str) -> bool:
        """Detect raw JSON/tool transport dumps copied into final answers."""
        stripped = str(text or "").strip()
        if not stripped:
            return False
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                payload = json.loads(stripped)
            except (ValueError, TypeError):
                payload = None
            if isinstance(payload, list) and payload and all(
                isinstance(item, dict) for item in payload
            ):
                return True
        lower = stripped.lower()
        return '"tool_calls"' in lower or '"tool_result"' in lower
