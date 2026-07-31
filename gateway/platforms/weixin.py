"""Weixin (微信公众平台 / WeChat Official Account) gateway adapter for NEXUS.

Supports two complementary surfaces:

* **Customer-service send (outbound)**: requires ``WX_APPID`` (alias
  ``WEIXIN_APPID``) and ``WX_APPSECRET`` (alias ``WEIXIN_APPSECRET``). A
  cached ``access_token`` is fetched from ``/cgi-bin/token`` and used to push
  customer-service text messages via ``/cgi-bin/message/custom/send``.
* **Callback (inbound)**: messages reach NEXUS through the Official Account
  callback URL. The platform verifies ownership with a SHA1 signature over the
  sorted ``(token, timestamp, nonce)`` (plaintext mode) or
  ``(token, timestamp, nonce, echostr)`` (URL verification handshake).
  Encrypted callbacks (AES-256-CBC, PKCS7) are decrypted when the optional
  ``pycryptodome`` dependency is installed.

The adapter is **env-gated**: ``connect()`` returns ``False`` unless appid +
appsecret are present, and the inbound XML parsing and signature computation
are pure functions tested without network access or live credentials.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

WX_API_BASE = "https://api.weixin.qq.com/cgi-bin"

WX_APPID_ENV = ("WX_APPID", "WEIXIN_APPID")
WX_APPSECRET_ENV = ("WX_APPSECRET", "WEIXIN_APPSECRET")
WX_TOKEN_ENV = ("WX_TOKEN", "WEIXIN_TOKEN")
WX_AES_KEY_ENV = ("WX_ENCODING_AES_KEY", "WEIXIN_ENCODING_AES_KEY")

try:  # pragma: no cover - exercised by presence/absence of pycryptodome
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    HAS_CRYPTO = True
except Exception:  # pragma: no cover - optional dependency absent
    HAS_CRYPTO = False
    AES = None  # type: ignore[assignment]
    unpad = None  # type: ignore[assignment]
    logger.warning(
        "pycryptodome not installed — Weixin encrypted callback decryption "
        "disabled. Install with: pip install pycryptodome"
    )


def _sha1_signature(*parts: str) -> str:
    """Weixin signature = SHA1 of the lexicographically sorted parts, joined."""
    items = sorted(parts)
    raw = "".join(items).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


class WeixinAdapter(BasePlatformAdapter):
    """NEXUS Weixin (WeChat Official Account) Adapter."""

    name = "weixin"
    has_crypto = HAS_CRYPTO
    required_env = WX_APPID_ENV + WX_APPSECRET_ENV

    def __init__(
        self,
        appid: str = "",
        appsecret: str = "",
        token: str = "",
        encoding_aes_key: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("weixin")
        self.appid = appid or self._first_env(WX_APPID_ENV)
        self.appsecret = appsecret or self._first_env(WX_APPSECRET_ENV)
        self.token = token or self._first_env(WX_TOKEN_ENV)
        self.encoding_aes_key = encoding_aes_key or self._first_env(WX_AES_KEY_ENV)
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @staticmethod
    def _first_env(names) -> str:
        for name in names:
            val = os.getenv(name, "")
            if val:
                return val
        return ""

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True only when both appid and appsecret are present."""
        return bool(self.appid and self.appsecret)

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "Weixin adapter unavailable: set WX_APPID and WX_APPSECRET "
                "(aliases WEIXIN_APPID / WEIXIN_APPSECRET)"
            )
            return False

        try:
            self._client = httpx.AsyncClient(base_url=WX_API_BASE, timeout=self.timeout)
            if not await self._fetch_access_token():
                return False
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"Weixin connection failed: {e}")
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
    # Token management
    # ------------------------------------------------------------------ #
    async def _fetch_access_token(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.get(
                "/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.appid,
                    "secret": self.appsecret,
                },
            )
            data = resp.json()
            if "access_token" not in data:
                logger.error(f"Weixin token fetch failed: {data.get('errmsg')}")
                return False
            self._access_token = data.get("access_token")
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200)) - 60
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"Weixin token fetch failed: {e}")
            return False

    async def _ensure_token(self) -> bool:
        # A token is valid when present and unexpired. ``_token_expires_at == 0``
        # means the token was injected without expiry metadata (e.g. in tests)
        # and should be trusted as-is.
        if self._access_token and (
            self._token_expires_at == 0.0 or self._token_expires_at > time.time()
        ):
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
        if not await self._ensure_token():
            return SendResult(success=False, error="Token unavailable")

        payload = {
            "touser": chat_id,
            "msgtype": "text",
            "text": {"content": text},
        }
        if reply_to:
            # The customer-service message API does not support true threaded
            # replies; surface the original message reference for debugging.
            payload["customservice"] = {"kf_account": reply_to}

        try:
            resp = await self._client.post(
                "/message/custom/send",
                params={"access_token": self._access_token},
                json=payload,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                return SendResult(
                    success=False, error=data.get("errmsg", "weixin send failed")
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
        """Validate a Weixin URL verification handshake signature."""
        expected = _sha1_signature(token, timestamp, nonce, echostr)
        return expected == msg_signature

    @staticmethod
    def verify_signature(
        token: str, timestamp: str, nonce: str, msg_signature: str
    ) -> bool:
        """Validate a Weixin callback message signature (plaintext mode)."""
        expected = _sha1_signature(token, timestamp, nonce)
        return expected == msg_signature

    @staticmethod
    def decrypt_message(encoding_aes_key: str, encrypt_b64: str) -> Optional[str]:
        """Decrypt a Weixin callback ``encrypt`` field (AES-256-CBC, PKCS7).

        Returns the plaintext XML, or ``None`` when ``pycryptodome`` is not
        installed or decryption fails.
        """
        if not HAS_CRYPTO:
            logger.warning("Weixin decrypt unavailable: pycryptodome missing")
            return None
        try:
            key = (encoding_aes_key + "=").encode("utf-8")
            key = key if len(key) == 32 else key[:32]
            iv = key[:16]
            cipher = AES.new(key, AES.MODE_CBC, iv)  # type: ignore[arg-type]
            ciphertext = _b64decode(encrypt_b64)
            plain = cipher.decrypt(ciphertext)
            plain = unpad(plain, AES.block_size)  # type: ignore[arg-type]
            # structure: random(16) + msg_len(4, big-endian) + msg + appid
            msg_len = int.from_bytes(plain[16:20], "big")
            content = plain[20 : 20 + msg_len]
            return content.decode("utf-8")
        except Exception as e:  # pragma: no cover - crypto dependent
            logger.error(f"Weixin decrypt failed: {e}")
            return None

    @staticmethod
    def parse_incoming(xml_text: str) -> Optional[MessageEvent]:
        """Parse Weixin callback XML into a :class:`MessageEvent`.

        Only ``text`` messages are surfaced; events, images, etc. return
        ``None`` for this adapter's default pipeline. Pure / synchronous for
        unit testing.
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
        receiver = _text("ToUserName")
        msg_id = _text("MsgId")

        if not content:
            return None

        return MessageEvent(
            text=content,
            sender_id=sender,
            chat_id=sender or receiver,
            platform="weixin",
            message_type="text",
            message_id=msg_id,
        )


def _b64decode(data: str) -> bytes:
    """Base64 decode with URL-safe handling for Weixin ``encrypt`` fields."""
    import base64

    try:
        return base64.b64decode(data)
    except Exception:
        return base64.b64decode(data + "=" * (-len(data) % 4))
