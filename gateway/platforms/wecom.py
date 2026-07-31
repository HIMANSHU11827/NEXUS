"""WeCom (企业微信 / WeChat Work) gateway adapter for NEXUS.

Two operating modes are supported:

* **App mode** (bidirectional): requires ``WECOM_CORPID``, ``WECOM_CORPSECRET``
  and ``WECOM_AGENTID``. Messages are sent through the application message API
  (``message/send``) using a cached ``access_token``. Inbound messages arrive
  via the application callback URL as encrypted XML (AES-256-CBC) — the
  signature verification and decryption helpers are provided, with the
  crypto portion guarded behind an optional ``pycryptodome`` dependency.
* **Webhook robot mode** (outbound only): requires only ``WECOM_WEBHOOK_KEY``.
  Messages are posted to the group robot webhook endpoint.

The adapter is **env-gated**: ``connect()`` returns ``False`` unless the
appropriate environment variables are present, and the inbound XML parsing and
URL/callback signature verification are pure functions so they can be unit
tested without any network access or live credentials.
"""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

# Env var groups recognised by this adapter.
WECOM_APP_ENV = ("WECOM_CORPID", "WECOM_CORPSECRET", "WECOM_AGENTID")
WECOM_WEBHOOK_ENV = "WECOM_WEBHOOK_KEY"

try:  # pragma: no cover - exercised by presence/absence of pycryptodome
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    HAS_CRYPTO = True
except Exception:  # pragma: no cover - optional dependency absent
    HAS_CRYPTO = False
    AES = None  # type: ignore[assignment]
    unpad = None  # type: ignore[assignment]
    logger.warning(
        "pycryptodome not installed — WeCom inbound callback decryption disabled. "
        "Install with: pip install pycryptodome"
    )


def _sha1_signature(*parts: str) -> str:
    """WeCom signature = SHA1 of the lexicographically sorted parts, concatenated."""
    import hashlib

    items = sorted(parts)
    raw = "".join(items).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


class WeComAdapter(BasePlatformAdapter):
    """NEXUS WeCom (WeChat Work) Adapter."""

    name = "wecom"
    has_crypto = HAS_CRYPTO
    required_env = WECOM_APP_ENV

    def __init__(
        self,
        corpid: str = "",
        corpsecret: str = "",
        agentid: str = "",
        webhook_key: str = "",
        token: str = "",
        encoding_aes_key: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("wecom")
        self.corpid = corpid or os.getenv("WECOM_CORPID", "")
        self.corpsecret = corpsecret or os.getenv("WECOM_CORPSECRET", "")
        self.agentid = str(agentid or os.getenv("WECOM_AGENTID", ""))
        self.webhook_key = webhook_key or os.getenv(WECOM_WEBHOOK_ENV, "")
        self.token = token or os.getenv("WECOM_CALLBACK_TOKEN", "")
        self.encoding_aes_key = encoding_aes_key or os.getenv("WECOM_ENCODING_AES_KEY", "")
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        app_configured = bool(self.corpid and self.corpsecret and self.agentid)
        if self.webhook_key and not app_configured:
            self._mode = "webhook"
        elif app_configured:
            self._mode = "app"
        else:
            self._mode = None  # type: ignore[assignment]

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True when either app credentials or a webhook key are present."""
        if self._mode == "webhook":
            return bool(self.webhook_key)
        if self._mode == "app":
            return bool(self.corpid and self.corpsecret and self.agentid)
        return False

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "WeCom adapter unavailable: set WECOM_CORPID/WECOM_CORPSECRET/"
                "WECOM_AGENTID (app mode) or WECOM_WEBHOOK_KEY (robot mode)"
            )
            return False

        try:
            self._client = httpx.AsyncClient(base_url=WECOM_API_BASE, timeout=self.timeout)

            if self._mode == "app":
                if not await self._fetch_access_token():
                    return False

            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"WeCom connection failed: {e}")
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
                params={"corpid": self.corpid, "corpsecret": self.corpsecret},
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.error(f"WeCom gettoken failed: {data.get('errmsg')}")
                return False
            self._access_token = data.get("access_token")
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200)) - 60
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"WeCom token fetch failed: {e}")
            return False

    async def _ensure_token(self) -> bool:
        if self._mode != "app":
            return True
        if self._access_token and self._token_expires_at > time.time():
            return True
        return await self._fetch_access_token()

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")

        try:
            if self._mode == "webhook":
                url = "/webhook/send"
                params = {"key": self.webhook_key}
                payload = {"msgtype": "text", "text": {"content": text}}
            else:
                if not await self._ensure_token():
                    return SendResult(success=False, error="Token unavailable")
                url = "/message/send"
                params = {"access_token": self._access_token}
                content = text
                if reply_to:
                    content = f"@{reply_to}\n{text}"
                payload = {
                    "touser": chat_id or "@all",
                    "msgtype": "text",
                    "agentid": self.agentid,
                    "text": {"content": content},
                }

            resp = await self._client.post(url, params=params, json=payload)
            data = resp.json()
            if data.get("errcode", 0) != 0:
                return SendResult(
                    success=False, error=data.get("errmsg", "wecom send failed")
                )
            return SendResult(success=True, message_id=str(data.get("msgid", "")))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Inbound: signature verification + parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_url(
        token: str, timestamp: str, nonce: str, echostr: str, msg_signature: str
    ) -> bool:
        """Validate a WeCom URL verification handshake signature."""
        expected = _sha1_signature(token, timestamp, nonce, echostr)
        return expected == msg_signature

    @staticmethod
    def verify_signature(
        token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str
    ) -> bool:
        """Validate a WeCom callback message signature."""
        expected = _sha1_signature(token, timestamp, nonce, encrypt)
        return expected == msg_signature

    @staticmethod
    def decrypt_message(encoding_aes_key: str, encrypt_b64: str) -> Optional[str]:
        """Decrypt a WeCom callback ``encrypt`` field (AES-256-CBC).

        Returns the plaintext XML, or ``None`` when ``pycryptodome`` is not
        installed or decryption fails.
        """
        if not HAS_CRYPTO:
            logger.warning("WeCom decrypt unavailable: pycryptodome missing")
            return None
        try:
            key = (encoding_aes_key + "=").encode("utf-8")
            key = key if len(key) == 32 else key[:32]
            iv = key[:16]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            ciphertext = _b64decode(encrypt_b64)
            plain = cipher.decrypt(ciphertext)
            plain = unpad(plain, AES.block_size)
            # structure: random(16) + msg_len(4, big-endian) + msg + corp_id
            msg_len = int.from_bytes(plain[16:20], "big")
            content = plain[20 : 20 + msg_len]
            return content.decode("utf-8")
        except Exception as e:  # pragma: no cover - crypto dependent
            logger.error(f"WeCom decrypt failed: {e}")
            return None

    @staticmethod
    def parse_incoming(xml_text: str) -> Optional[MessageEvent]:
        """Parse decrypted WeCom callback XML into a :class:`MessageEvent`.

        Only ``text`` messages are surfaced; other message types (events,
        images, etc.) return ``None`` for this adapter's default pipeline.
        Pure / synchronous for unit testing.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        def _text(tag: str) -> str:
            node = root.find(tag)
            if node is None:
                return ""
            return (node.text or "").strip()

        msg_type = _text("MsgType")
        if msg_type != "text":
            return None

        content = _text("Content")
        sender = _text("FromUserName")
        agent_id = _text("AgentID")
        msg_id = _text("MsgId")

        if not content:
            return None

        return MessageEvent(
            text=content,
            sender_id=sender,
            chat_id=sender or agent_id,
            platform="wecom",
            message_type="text",
            message_id=msg_id,
        )


def _b64decode(data: str) -> bytes:
    """Base64 decode with URL-safe handling for WeCom ``encrypt`` fields."""
    import base64

    try:
        return base64.b64decode(data)
    except Exception:
        return base64.b64decode(data + "=" * (-len(data) % 4))
