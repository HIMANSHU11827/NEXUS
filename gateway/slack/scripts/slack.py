"""Slack platform adapter — sends/receives messages via Slack Bot."""
__version__ = "1.0.0"

import logging
import os
from typing import Any, Dict, List, Optional

import requests as req
from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class SlackAdapter(BasePlatformAdapter):
    name: str = "slack"
    version: str = "1.0"
    requires_env: List[str] = ["SLACK_TOKEN"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = os.environ.get("SLACK_TOKEN", "")
        self._api_base = "https://slack.com/api"

    def connect(self) -> bool:
        if not self._token:
            logger.error("SLACK_TOKEN not set")
            return False
        try:
            resp = req.post(f"{self._api_base}/auth.test", headers={
                "Authorization": f"Bearer {self._token}",
            }, timeout=10)
            if resp.status_code == 200 and resp.json().get("ok"):
                self._connected = True
                logger.info("Slack adapter connected")
                return True
            logger.error(f"Slack auth failed: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Slack connect failed: {e}")
            return False

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "slack"}
        try:
            resp = req.post(f"{self._api_base}/chat.postMessage", headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }, json={
                "channel": target,
                "text": content,
            }, timeout=10)
            data = resp.json()
            if data.get("ok"):
                return {"sent": True, "channel": target, "platform": "slack"}
            return {"error": data.get("error", "unknown"), "platform": "slack"}
        except Exception as e:
            return {"error": str(e), "platform": "slack"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        return []
