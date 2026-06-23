"""Meta/Messenger platform adapter — sends messages via Meta Graph API."""
__version__ = "1.0.0"

import logging
import os
from typing import Any, Dict, List, Optional

import requests as req
from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class MetaAdapter(BasePlatformAdapter):
    name: str = "meta"
    version: str = "1.0"
    requires_env: List[str] = ["META_PAGE_TOKEN"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = os.environ.get("META_PAGE_TOKEN", "")
        self._api_base = "https://graph.facebook.com/v18.0/me"

    def connect(self) -> bool:
        if not self._token:
            logger.error("META_PAGE_TOKEN not set")
            return False
        self._connected = True
        logger.info("Meta adapter ready")
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "meta"}
        try:
            resp = req.post(f"{self._api_base}/messages", params={
                "access_token": self._token,
            }, json={
                "recipient": {"id": target},
                "message": {"text": content},
            }, timeout=10)
            if resp.status_code == 200:
                return {"sent": True, "to": target, "platform": "meta"}
            return {"error": resp.text, "platform": "meta"}
        except Exception as e:
            return {"error": str(e), "platform": "meta"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        return []
