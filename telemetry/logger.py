import os
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

class NexusTelemetry:
    """
    Advanced Telemetry and Logging system for NEXUS AI.
    Handles structured logging, performance tracking, and error reporting.
    """
    def __init__(self, log_dir: Optional[str] = None):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not log_dir:
            log_dir = os.path.join(root, "logs", "telemetry")
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_id = f"session_{int(time.time())}"
        self.log_file = self.log_dir / f"{self.session_id}.jsonl"
        
        # Setup standard logging
        self.logger = logging.getLogger("NEXUS_CORE")
        self.logger.setLevel(logging.INFO)
        
        # File handler
        if not any(isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == str(self.log_dir / "nexus_system.log") for handler in self.logger.handlers):
            fh = logging.FileHandler(self.log_dir / "nexus_system.log")
            fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(fh)

    def log_event(self, event_type: str, data: Dict[str, Any], level: str = "INFO"):
        """Logs a structured event to the telemetry file."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "level": level,
            "session_id": self.session_id,
            "data": data
        }
        
        # Write to JSONL
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as exc:
            self.logger.warning("Failed to write telemetry event: %s", exc)
            
        # Log to standard logger
        log_msg = f"[{event_type}] {json.dumps(data)}"
        if level == "INFO":
            self.logger.info(log_msg)
        elif level == "WARNING":
            self.logger.warning(log_msg)
        elif level == "ERROR":
            self.logger.error(log_msg)

    def log_tool_usage(self, tool_name: str, params: Dict[str, Any], duration: float, success: bool, error: Optional[str] = None):
        """Logs tool execution details."""
        self.log_event("TOOL_EXECUTION", {
            "tool": tool_name,
            "params": params,
            "duration": duration,
            "success": success,
            "error": error
        })

    def log_performance(self, metric: str, value: float, units: str = "ms"):
        """Logs performance metrics."""
        self.log_event("PERFORMANCE_METRIC", {
            "metric": metric,
            "value": value,
            "units": units
        })

# Global instance for easy access
telemetry = NexusTelemetry()
