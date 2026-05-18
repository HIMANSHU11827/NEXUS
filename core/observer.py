"""
NEXUS TELEMETRY OBSERVER — The "Eyes" of the Self-Learning Kernel.
Tracks tool performance, latency, and failure patterns in real-time.
Essential for Phase 2: Metacognitive Self-Correction.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class NexusObserver:
    """
    Central telemetry tracker.
    Stores episodic 'Experiences' to train the self-learning loop.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.telemetry_path = os.path.join(root_dir, "logs", "telemetry.jsonl")
        os.makedirs(os.path.dirname(self.telemetry_path), exist_ok=True)

    def log_event(self, event_type: str, data: Dict[str, Any]):
        """Logs a telemetry event to a structured JSONL file."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data,
        }
        try:
            with open(self.telemetry_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as exc:
            logger.warning("Failed to write observer event: %s", exc)

    def log_tool_execution(self, tool_name: str, params: Dict[str, Any], result: str, duration: float):
        """Standardized tool execution logging."""
        success = "[TOOL_ERROR]" not in result and "[ERR]" not in result
        self.log_event("TOOL_EXECUTE", {
            "tool": tool_name,
            "params": params,
            "success": success,
            "duration": duration,
            "result_summary": result[:200] if result else "",
        })

    def log_reasoning_step(self, plan: str, turn: int):
        """Logs a major reasoning decision/plan."""
        self.log_event("REASONING_PLAN", {
            "turn": turn,
            "plan_summary": plan[:500]
        })

    def get_failure_patterns(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Analyzes recent logs to find recurring tool failures."""
        if not os.path.exists(self.telemetry_path):
            return []

        failures = []
        try:
            with open(self.telemetry_path, "r", encoding="utf-8") as f:
                for line in f:
                    event = json.loads(line)
                    if event["type"] == "TOOL_EXECUTE" and not event["data"]["success"]:
                        failures.append(event)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read observer telemetry: %s", exc)
        return failures[-limit:]

    def reset_telemetry(self):
        """Clears telemetry for a fresh learning cycle."""
        if os.path.exists(self.telemetry_path):
            os.remove(self.telemetry_path)
