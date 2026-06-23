"""Telegram platform adapter — sends/receives messages via Telegram Bot API."""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests as req
from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class TelegramAdapter(BasePlatformAdapter):
    name: str = "telegram"
    version: str = "1.0"
    requires_env: List[str] = ["TELEGRAM_TOKEN"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = os.environ.get("TELEGRAM_TOKEN", "")
        self._api_base = f"https://api.telegram.org/bot{self._token}"
        self._last_update_id = 0

    def connect(self) -> bool:
        if not self._token:
            logger.error("TELEGRAM_TOKEN not set")
            return False
        try:
            resp = req.get(f"{self._api_base}/getMe", timeout=10)
            if resp.status_code == 200:
                self._connected = True
                logger.info("Telegram adapter connected")
                return True
            logger.error(f"Telegram auth failed: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram connect failed: {e}")
            return False

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "telegram"}
        try:
            resp = req.post(f"{self._api_base}/sendMessage", json={
                "chat_id": target,
                "text": content,
                "parse_mode": kwargs.get("parse_mode", "Markdown"),
            }, timeout=10)
            if resp.status_code == 200:
                return {"sent": True, "chat_id": target, "platform": "telegram"}
            return {"error": resp.text, "platform": "telegram"}
        except Exception as e:
            return {"error": str(e), "platform": "telegram"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        if not self._connected:
            return []
        try:
            resp = req.get(f"{self._api_base}/getUpdates", json={
                "offset": self._last_update_id + 1,
                "timeout": int(timeout),
            }, timeout=timeout + 5)
            if resp.status_code == 200:
                data = resp.json()
                messages = []
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    if "message" in update:
                        msg = update["message"]
                        messages.append({
                            "platform": "telegram",
                            "chat_id": str(msg["chat"]["id"]),
                            "text": msg.get("text", ""),
                            "from_id": str(msg["from"]["id"]),
                            "from_name": msg["from"].get("first_name", ""),
                            "raw": msg,
                        })
                return messages
        except Exception:
            pass
        return []
