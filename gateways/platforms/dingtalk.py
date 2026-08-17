"""NEXUS DingTalk (钉钉) gateway adapter.

Two operating modes are supported:

* **Robot webhook mode** (outbound): requires ``DINGTALK_WEBHOOK_ACCESS_TOKEN``
  (alias ``DINGTALK_ROBOT_TOKEN``) or a full ``DINGTALK_WEBHOOK`` URL. Messages
  are POSTed to the custom-robot ``/robot/send`` endpoint. When
  ``DINGTALK_WEBHOOK_SECRET`` (alias ``DINGTALK_ROBOT_SECRET``) is set, the
  request is signed with DingTalk's HMAC-SHA256 "加签" scheme to harden the
  robot against unauthorized calls.
* **App mode** (bidirectional via the agent API): requires ``DINGTALK_APP_KEY``
  and ``DINGTALK_APP_SECRET``. An ``access_token`` is fetched from ``/gettoken``
  and messages are sent through the ``corpconversation/asyncsend_v2`` API.

Inbound robot group callbacks (DingTalk "机器人接收消息") arrive as a JSON
payload and are normalised by :meth:`DingtalkAdapter.parse_event`. The inbound
signature can be verified with :meth:`DingtalkAdapter.verify_inbound_signature`.

The adapter is **env-gated**: ``connect()`` returns ``False`` unless a mode is
configured, and all parsing / signature logic is pure so it can be unit tested
without network access or live credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
from typing import Optional, Tuple

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

DINGTALK_API_BASE = "https://oapi.dingtalk.com"
DINGTALK_ROBOT_SEND = f"{DINGTALK_API_BASE}/robot/send"

# Env var groups recognised by this adapter.
DINGTALK_WEBHOOK_TOKEN_ENV = ("DINGTALK_WEBHOOK_ACCESS_TOKEN", "DINGTALK_ROBOT_TOKEN")
DINGTALK_WEBHOOK_URL_ENV = ("DINGTALK_WEBHOOK",)
DINGTALK_WEBHOOK_SECRET_ENV = ("DINGTALK_WEBHOOK_SECRET", "DINGTALK_ROBOT_SECRET")
DINGTALK_APP_KEY_ENV = ("DINGTALK_APP_KEY",)
DINGTALK_APP_SECRET_ENV = ("DINGTALK_APP_SECRET",)
DINGTALK_AGENT_ID_ENV = ("DINGTALK_AGENT_ID",)


def _compute_robot_sign(secret: str, timestamp: str) -> str:
    """DingTalk robot "加签" signature (HMAC-SHA256, base64, url-encoded).

    The signed string is ``"<timestamp>\\n<secret>"`` keyed with ``secret``;
    the resulting digest is base64-encoded and URL-quoted. This is the exact
    scheme DingTalk uses both to sign outbound robot calls and to authenticate
    inbound robot callbacks.
    """
    if not secret:
        return ""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("ascii"))


class DingtalkAdapter(BasePlatformAdapter):
    """NEXUS DingTalk (钉钉) Adapter."""

    name = "dingtalk"
    required_env = (
        "DINGTALK_WEBHOOK_ACCESS_TOKEN",
        "DINGTALK_WEBHOOK",
        "DINGTALK_APP_KEY",
        "DINGTALK_APP_SECRET",
    )

    def __init__(
        self,
        webhook_access_token: str = "",
        webhook_url: str = "",
        webhook_secret: str = "",
        app_key: str = "",
        app_secret: str = "",
        agent_id: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("dingtalk")
        self.webhook_access_token = (
            webhook_access_token or self._first_env(DINGTALK_WEBHOOK_TOKEN_ENV)
        )
        self.webhook_url = webhook_url or self._first_env(DINGTALK_WEBHOOK_URL_ENV)
        self.webhook_secret = webhook_secret or self._first_env(
            DINGTALK_WEBHOOK_SECRET_ENV
        )
        self.app_key = app_key or self._first_env(DINGTALK_APP_KEY_ENV)
        self.app_secret = app_secret or self._first_env(DINGTALK_APP_SECRET_ENV)
        self.agent_id = str(agent_id or self._first_env(DINGTALK_AGENT_ID_ENV))
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        robot_configured = bool(self.webhook_access_token or self.webhook_url)
        app_configured = bool(self.app_key and self.app_secret)
        if robot_configured:
            self._mode = "robot"
        elif app_configured:
            self._mode = "app"
        else:
            self._mode = None  # type: ignore[assignment]

    @staticmethod
    def _first_env(names):
        for name in names:
            val = os.getenv(name, "")
            if val:
                return val
        return ""

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True when either robot (token/url) or app (key+secret) is set."""
        if self._mode == "robot":
            return bool(self.webhook_access_token or self.webhook_url)
        if self._mode == "app":
            return bool(self.app_key and self.app_secret)
        return False

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "DingTalk adapter unavailable: set DINGTALK_WEBHOOK_ACCESS_TOKEN "
                "(robot mode) or DINGTALK_APP_KEY + DINGTALK_APP_SECRET (app mode)"
            )
            return False

        try:
            self._client = httpx.AsyncClient(
                base_url=DINGTALK_API_BASE, timeout=self.timeout
            )
            if self._mode == "app":
                if not await self._fetch_access_token():
                    return False
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"DingTalk connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None
        self._access_token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ #
    # Token management (app mode)
    # ------------------------------------------------------------------ #
    async def _fetch_access_token(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.get(
                "/gettoken",
                params={"appkey": self.app_key, "appsecret": self.app_secret},
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.error(f"DingTalk gettoken failed: {data.get('errmsg')}")
                return False
            self._access_token = data.get("access_token")
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200)) - 60
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"DingTalk token fetch failed: {e}")
            return False

    async def _ensure_token(self) -> bool:
        if self._mode != "app":
            return True
        if self._access_token and self._token_expires_at > time.time():
            return True
        return await self._fetch_access_token()

    # ------------------------------------------------------------------ #
    # Outbound URL + bodies
    # ------------------------------------------------------------------ #
    def _robot_send_url(self) -> str:
        if self.webhook_url:
            return self.webhook_url
        url = f"{DINGTALK_ROBOT_SEND}?access_token={self.webhook_access_token}"
        if self.webhook_secret:
            ts = str(round(time.time() * 1000))
            sign = _compute_robot_sign(self.webhook_secret, ts)
            url += f"&timestamp={ts}&sign={sign}"
        return url

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")

        try:
            if self._mode == "app":
                if not await self._ensure_token():
                    return SendResult(success=False, error="Token unavailable")
                url = "/topapi/message/corpconversation/asyncsend_v2"
                msg = {"msgtype": "text", "text": {"content": text}}
                payload = {
                    "agent_id": self.agent_id,
                    "userid": chat_id,
                    "msg": msg,
                }
                resp = await self._client.post(url, json=payload)
            else:
                url = self._robot_send_url()
                payload = {"msgtype": "text", "text": {"content": text}}
                resp = await self._client.post(url, json=payload)

            data = resp.json()
            if data.get("errcode", 0) != 0:
                return SendResult(
                    success=False, error=data.get("errmsg", "dingtalk send failed")
                )
            message_id = data.get("messageId") or data.get("task_id") or data.get("request_id")
            return SendResult(success=True, message_id=str(message_id) if message_id else None)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Inbound: signature verification + parsing
    # ------------------------------------------------------------------ #
    @classmethod
    def verify_inbound_signature(cls, secret: str, timestamp: str, signature: str) -> bool:
        """Verify a DingTalk inbound robot callback signature.

        Inbound robot callbacks are signed with the same "加签" scheme used for
        outbound calls: the caller supplies a ``timestamp`` and a ``sign``; we
        recompute the expected signature from the configured ``secret`` and
        compare in constant time.
        """
        if not secret or not signature:
            return False
        expected = _compute_robot_sign(secret, timestamp)
        return hmac.compare_digest(expected, signature)

    @classmethod
    def parse_event(cls, payload: dict) -> Optional[MessageEvent]:
        """Normalise a DingTalk inbound payload into a :class:`MessageEvent`.

        Handles two shapes:

        * **Robot group callback** — the top-level ``msgtype`` is ``"text"`` and
          ``text.content`` holds the body. ``senderId`` / ``conversationId`` /
          ``msgId`` identify the sender.
        * **URL verification challenge** — returns ``None`` for the event but the
          ``challenge`` is surfaced via :meth:`handle_webhook_payload`.

        Pure / synchronous for unit testing.
        """
        if not isinstance(payload, dict):
            return None

        # URL verification handshake (event subscription style).
        if payload.get("type") == "check_url" and "challenge" in payload:
            return None

        if payload.get("msgtype") != "text":
            return None

        text = (payload.get("text") or {}).get("content", "")
        sender_id = payload.get("senderId") or payload.get("senderNick") or ""
        chat_id = payload.get("conversationId") or payload.get("cid") or ""
        msg_id = payload.get("msgId")

        if not text or not sender_id:
            return None

        return MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id or sender_id,
            platform="dingtalk",
            message_type="text",
            message_id=msg_id,
            reply_to_id=payload.get("robotCode"),
        )

    async def handle_webhook_payload(self, payload: dict) -> Optional[MessageEvent]:
        """Convenience hook used by a webhook receiver.

        Parses the payload and dispatches a parsed event to the registered
        message handler, returning the emitted :class:`MessageEvent` (or
        ``None`` when the payload is not a recognised message).
        """
        event = self.parse_event(payload)
        if event is not None and self._on_message:
            result = self._on_message(event)
            if hasattr(result, "__await__"):
                await result
        return event
