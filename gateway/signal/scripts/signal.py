"""Signal platform adapter — sends messages via Signal CLI."""

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class SignalAdapter(BasePlatformAdapter):
    name: str = "signal"
    version: str = "1.0"
    requires_env: List[str] = ["SIGNAL_NUMBER"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._number = os.environ.get("SIGNAL_NUMBER", "")
        self._cli_path = os.environ.get("SIGNAL_CLI", "signal-cli")

    def connect(self) -> bool:
        if not self._number:
            logger.error("SIGNAL_NUMBER not set")
            return False
        try:
            subprocess.run([self._cli_path, "--version"], capture_output=True, timeout=5)
            self._connected = True
            logger.info("Signal adapter ready")
            return True
        except FileNotFoundError:
            logger.warning("signal-cli not found in PATH")
            return False
        except Exception as e:
            logger.error(f"Signal connect failed: {e}")
            return False

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "signal"}
        try:
            result = subprocess.run(
                [self._cli_path, "-u", self._number, "send", "-m", content, target],
                capture_output=True, timeout=15, text=True,
            )
            if result.returncode == 0:
                return {"sent": True, "to": target, "platform": "signal"}
            return {"error": result.stderr, "platform": "signal"}
        except Exception as e:
            return {"error": str(e), "platform": "signal"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        return []
