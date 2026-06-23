"""WhatsApp platform adapter — sends/receives messages via WhatsApp Cloud API."""
__version__ = "1.0.0"

import logging
import os
from typing import Any, Dict, List, Optional

import requests as req
from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class WhatsAppAdapter(BasePlatformAdapter):
    name: str = "whatsapp"
    version: str = "1.0"
    requires_env: List[str] = ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = os.environ.get("WHATSAPP_TOKEN", "")
        self._phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
        self._api_base = "https://graph.facebook.com/v18.0"

    def connect(self) -> bool:
        if not self._token or not self._phone_id:
            logger.error("WHATSAPP_TOKEN or WHATSAPP_PHONE_ID not set")
            return False
        self._connected = True
        logger.info("WhatsApp adapter ready")
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "whatsapp"}
        try:
            url = f"{self._api_base}/{self._phone_id}/messages"
            resp = req.post(url, headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }, json={
                "messaging_product": "whatsapp",
                "to": target,
                "text": {"body": content},
            }, timeout=10)
            if resp.status_code == 200:
                return {"sent": True, "to": target, "platform": "whatsapp"}
            return {"error": resp.text, "platform": "whatsapp"}
        except Exception as e:
            return {"error": str(e), "platform": "whatsapp"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        return []
