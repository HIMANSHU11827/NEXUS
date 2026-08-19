"""Stuck-loop watchdog — detect and break non-progressing agent loops.

Inspired by OpenHands' StuckDetector and the direct_loop's stagnation
detector, but at a higher level: monitors the agent's overall progress
across turns, not just per-signature repeats.

Detects:
- Same tool called repeatedly with no progress (stagnation)
- Turn count exceeding expected bounds without completion
- Provider call failures in a streak (all calls failing)
- Context window exhaustion loops (compacting but not progressing)

When stuck, the watchdog can:
1. Force a finalization turn (tell the model to wrap up)
2. Inject a "you are stuck" message into the context
3. Force a different tool/model
4. Escalate to the operator (in 24/7 mode)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Configuration
_STALL_THRESHOLD = int(os.environ.get("NEXUS_STALL_THRESHOLD", "8") or 8)
_FAILURE_STREAK_LIMIT = int(os.environ.get("NEXUS_FAILURE_STREAK_LIMIT", "5") or 5)
_CONTEXT_EXHAUSTION_LIMIT = int(os.environ.get("NEXUS_CONTEXT_EXHAUSTION_LIMIT", "3") or 3)
_STUCK_TIMEOUT_SECONDS = float(os.environ.get("NEXUS_STUCK_TIMEOUT", "600") or 600)


@dataclass
class ToolCallRecord:
    """Record of a tool call for stagnation detection."""
    name: str
    params_hash: str
    result_hash: str
    success: bool
    timestamp: float


@dataclass
class WatchdogState:
    """Current state of the stuck detector."""
    turn_count: int = 0
    consecutive_failures: int = 0
    consecutive_context_exhaustions: int = 0
    recent_tool_calls: List[ToolCallRecord] = field(default_factory=list)
    last_progress_time: float = field(default_factory=time.time)
    stuck_detected: bool = False
    stuck_reason: str = ""
    finalization_triggered: bool = False


class StuckDetector:
    """Monitors agent loop progress and detects stuck conditions.

    The detector is turn-level (not round-level): it watches the overall
    trajectory of the agent across multiple model calls and tool executions.
    """

    def __init__(self):
        self.state = WatchdogState()
        self._action_signatures: Dict[str, int] = {}  # signature -> count

    def record_tool_call(
        self,
        name: str,
        params: Any,
        result: str,
        success: bool,
    ) -> None:
        """Record a tool call for stagnation analysis."""
        import hashlib
        import json

        params_str = json.dumps(params or {}, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:16]
        result_hash = hashlib.md5(str(result or "").encode()).hexdigest()[:16]
        signature = f"{name}:{params_hash}"

        record = ToolCallRecord(
            name=name,
            params_hash=params_hash,
            result_hash=result_hash,
            success=success,
            timestamp=time.time(),
        )
        self.state.recent_tool_calls.append(record)
        # Keep only recent calls
        if len(self.state.recent_tool_calls) > 50:
            self.state.recent_tool_calls = self.state.recent_tool_calls[-50:]

        # Track signature count for stagnation
        self._action_signatures[signature] = self._action_signatures.get(signature, 0) + 1

        if success:
            self.state.last_progress_time = time.time()
            self.state.consecutive_failures = 0
        else:
            self.state.consecutive_failures += 1

    def record_turn(self) -> None:
        """Record that a new turn has started."""
        self.state.turn_count += 1

    def record_context_exhaustion(self) -> None:
        """Record that the context was exhausted and compacted."""
        self.state.consecutive_context_exhaustions += 1

    def record_progress(self) -> None:
        """Record that meaningful progress was made."""
        self.state.last_progress_time = time.time()
        self.state.consecutive_failures = 0
        self.state.consecutive_context_exhaustions = 0
        self._action_signatures.clear()

    def check_stuck(self) -> Optional[str]:
        """Check if the agent is stuck; returns a reason string or None.

        Checks are ordered from most specific to most general.
        """
        now = time.time()

        # 1. Failure streak: all recent calls failed
        if self.state.consecutive_failures >= _FAILURE_STREAK_LIMIT:
            reason = (
                f"failure streak: {self.state.consecutive_failures} consecutive "
                f"tool failures (limit: {_FAILURE_STREAK_LIMIT})"
            )
            self.state.stuck_detected = True
            self.state.stuck_reason = reason
            return reason

        # 2. Context exhaustion loop: compacting repeatedly without progress
        if self.state.consecutive_context_exhaustions >= _CONTEXT_EXHAUSTION_LIMIT:
            reason = (
                f"context exhaustion loop: {self.state.consecutive_context_exhaustions} "
                f"compactions without progress (limit: {_CONTEXT_EXHAUSTION_LIMIT})"
            )
            self.state.stuck_detected = True
            self.state.stuck_reason = reason
            return reason

        # 3. Stagnation: same action signature repeated too many times
        for signature, count in self._action_signatures.items():
            if count >= _STALL_THRESHOLD:
                name = signature.split(":")[0]
                reason = (
                    f"stagnation: tool '{name}' called {count} times "
                    f"with identical parameters (limit: {_STALL_THRESHOLD})"
                )
                self.state.stuck_detected = True
                self.state.stuck_reason = reason
                return reason

        # 4. No progress timeout: nothing succeeded for too long
        time_since_progress = now - self.state.last_progress_time
        if time_since_progress > _STUCK_TIMEOUT_SECONDS and self.state.turn_count > 3:
            reason = (
                f"no progress timeout: {time_since_progress:.0f}s since last "
                f"successful action (limit: {_STUCK_TIMEOUT_SECONDS}s)"
            )
            self.state.stuck_detected = True
            self.state.stuck_reason = reason
            return reason

        return None

    def get_finalization_prompt(self) -> str:
        """Generate a prompt to force the agent to wrap up when stuck."""
        return (
            "FINALIZATION REQUIRED: You appear to be stuck. "
            "Stop calling tools and provide a final answer now. "
            "Report what was accomplished, what failed, and what remains. "
            "Do not call any more tools."
        )

    def get_unstick_prompt(self) -> str:
        """Generate a prompt to help the agent break out of a loop."""
        recent = self.state.recent_tool_calls[-5:]
        tools_called = [r.name for r in recent]
        return (
            f"WARNING: You are repeating the same actions without progress. "
            f"Recent tools: {tools_called}. "
            "Try a completely different approach. "
            "If the task is impossible with available tools, say so honestly "
            "instead of retrying the same failing strategy."
        )

    def reset(self) -> None:
        """Reset the detector for a new task."""
        self.state = WatchdogState()
        self._action_signatures.clear()

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the detector state."""
        return {
            "turn_count": self.state.turn_count,
            "consecutive_failures": self.state.consecutive_failures,
            "consecutive_context_exhaustions": self.state.consecutive_context_exhaustions,
            "stuck_detected": self.state.stuck_detected,
            "stuck_reason": self.state.stuck_reason,
            "time_since_progress": time.time() - self.state.last_progress_time,
            "unique_actions": len(self._action_signatures),
        }
