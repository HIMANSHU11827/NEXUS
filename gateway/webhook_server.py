"""
Lightweight Meta webhook server for WhatsApp / Facebook / Instagram,
plus inbound webhook routes for every NEXUS gateway platform that implements
an HTTP-accessible inbound parser (LINE, Teams, Google Chat, Feishu, Yuanbao,
QQBot, DingTalk, WeCom, Weixin, BlueBubbles).

The Meta routes are always registered (matching the original behaviour). The
per-platform ``/webhook/<platform>`` routes are only added by
:func:`build_platform_routes` when that platform's env credentials AND its
verification secret are present, so a platform that is not configured never
exposes an HTTP surface.

Run alongside the GatewayRunner to receive incoming messages from each
platform's webhook/callback API.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from typing import Dict, List

from aiohttp import web

logger = logging.getLogger("NEXUS-WEBHOOK")

routes = web.RouteTableDef()
_adapters: Dict[str, object] = {}
_verify_token: str = ""
_app_secret: str = ""

# Platforms that share the Meta Graph API payload shape.
_META_FAMILY = {"meta", "whatsapp", "facebook", "instagram"}

# Inbound shared-secret headers for platforms that lack a platform-native
# signature (Teams, Google Chat, BlueBubbles). Operators must configure the
# matching secret env var; the routes fail closed (401) when the header is
# absent or mismatched.
HEADER_AUTHORIZATION = "Authorization"
HEADER_WEBHOOK_SECRET = "X-Webhook-Secret"


@routes.get("/webhook/meta")
async def verify(request: web.Request) -> web.Response:
    """Meta webhook verification handshake."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == _verify_token:
        logger.info("Meta webhook verified.")
        return web.Response(text=challenge)
    return web.Response(status=403, text="Verification failed")


def compute_meta_signature(app_secret: str, raw_body: bytes) -> str:
    """Compute the ``sha256=...`` X-Hub-Signature-256 value for a raw body."""
    digest = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_meta_signature(app_secret: str, raw_body: bytes, signature: str) -> bool:
    """Constant-time check of the Meta ``X-Hub-Signature-256`` request header.

    Fails closed: returns False when no app secret is configured, the header is
    absent, or the signature does not match the computed HMAC.
    """
    if not app_secret or not signature:
        return False
    expected = compute_meta_signature(app_secret, raw_body)
    return hmac.compare_digest(expected, signature.lower())


@routes.post("/webhook/meta")
async def webhook(request: web.Request) -> web.Response:
    """Receive incoming Meta webhook events."""
    raw = await request.read()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_meta_signature(_app_secret, raw, signature):
        logger.warning("Rejecting Meta webhook: missing/invalid X-Hub-Signature-256")
        return web.Response(status=401, text="Unauthorized")

    try:
        payload = json.loads(raw.decode("utf-8"))
        logger.debug(f"Webhook payload: {json.dumps(payload)[:500]}...")

        for platform, adapter in _adapters.items():
            if platform not in _META_FAMILY:
                # Other platforms have their own route and signature scheme; do
                # not fan-out Meta payloads to them.
                continue
            try:
                if hasattr(adapter, "handle_webhook_payload"):
                    await adapter.handle_webhook_payload(payload)
            except Exception as e:
                logger.error(f"[{platform}] webhook handler error: {e}")

        return web.Response(status=200, text="EVENT_RECEIVED")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        return web.Response(status=400, text="Bad request")


# --------------------------------------------------------------------------- #
# Per-platform inbound webhook routes
#
# Each builder returns zero routes when the platform is not configured (no
# adapter registered and/or no verification secret present) and otherwise
# returns aiohttp ``RouteDef`` objects registered as ``/webhook/<platform>``.
# All routes verify the platform signature fail-closed: missing/invalid
# signature => 401 before the platform handler is ever called.
# --------------------------------------------------------------------------- #

def _adapter(platform: str):
    return _adapters.get(platform)


async def _dispatch_event(adapter, event) -> None:
    """Invoke an adapter's registered message handler for a parsed event.

    Some inbound parsers (``handle_inbound`` / WeCom+Weixin XML parsing) return
    a :class:`MessageEvent` without dispatching it, so the webhook server routes
    yield the event to ``adapter._on_message``. The adapter's ``_on_message``
    attribute is set by :meth:`BasePlatformAdapter.set_message_handler`.

    Re-delivered events (platform retries / duplicate callbacks) are dropped
    here before the gateway handler runs, using the shared ingress LRU.
    """
    if event is None:
        return
    # Ingress de-duplication shared with gateway/run.py. Lazy import keeps the
    # aiohttp-only webhook module free of the heavyweight gateway import graph
    # until a message actually arrives. The event is marked so the gateway
    # handler below does not double-count this same delivery.
    try:
        from gateway.run import mark_handled, seen_event
        if seen_event(event):
            adapter_name = getattr(adapter, "platform", type(adapter).__name__)
            logger.info(
                "Dropping duplicate webhook event for %s (message_id=%s)",
                adapter_name, getattr(event, "message_id", None),
            )
            return
        mark_handled(event)
    except Exception:  # degrade softly — never drop on dedupe machinery failure
        logger.debug("webhook dedupe check failed", exc_info=True)
    handler = getattr(adapter, "_on_message", None)
    if handler is None:
        return
    result = handler(event)
    if hasattr(result, "__await__"):
        await result


def _line_route() -> list:
    """LINE Messaging API — ``POST /webhook/line``.

    Signature: ``X-Line-Signature`` = base64(HMAC-SHA256(channel_secret, body)).
    """
    adapter = _adapter("line")
    if adapter is None or not getattr(adapter, "channel_secret", ""):
        return []
    verify = getattr(adapter, "verify_signature", None)
    if verify is None:
        return []

    async def line_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        signature = request.headers.get("X-Line-Signature", "")
        if not verify(raw, signature):
            logger.warning("Rejecting LINE webhook: missing/invalid X-Line-Signature")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            await adapter.handle_webhook_payload(payload)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"LINE webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

    return [web.post("/webhook/line", line_webhook)]


def _teams_route() -> list:
    """Microsoft Teams (Bot Framework) — ``POST /webhook/teams``.

    The Bot Framework authenticates callers with ``Authorization: Bearer
    <app/password token>``. We fail closed against ``TEAMS_CLIENT_SECRET`` or
    ``TEAMS_BOT_TOKEN`` (both surfaced on the adapter). The serialized access
    token validation covered by the real Bot Connector (AAD-decoded JWTs) is
    intentionally *not* simulated here; the bearer must match the configured
    secret exactly.
    """
    adapter = _adapter("teams")
    if adapter is None:
        return []
    secret = getattr(adapter, "client_secret", "") or getattr(adapter, "bot_token", "")
    if not secret:
        return []
    if not hasattr(adapter, "handle_webhook_payload"):
        return []

    async def teams_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        auth = request.headers.get(HEADER_AUTHORIZATION, "")
        provided = auth[len("Bearer "):] if auth.lower().startswith("bearer ") else ""
        if not provided or not hmac.compare_digest(secret, provided):
            logger.warning("Rejecting Teams webhook: missing/invalid Authorization bearer")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            await adapter.handle_webhook_payload(payload)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"Teams webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

    return [web.post("/webhook/teams", teams_webhook)]


def _google_chat_route() -> list:
    """Google Chat App — ``POST /webhook/google_chat``.

    Google's Chat API does not sign HTTP callbacks, so we fail closed against a
    shared secret configured via ``GOOGLE_CHAT_WEBHOOK_SECRET`` and sent in the
    ``Authorization: Bearer`` header. ``handle_inbound`` normalises the payload;
    the resulting :class:`MessageEvent` is dispatched by the route.
    """
    adapter = _adapter("google_chat")
    if adapter is None:
        return []
    secret = os.getenv("GOOGLE_CHAT_WEBHOOK_SECRET", "")
    if not secret:
        return []
    if not hasattr(adapter, "handle_inbound"):
        return []

    async def google_chat_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        auth = request.headers.get(HEADER_AUTHORIZATION, "")
        provided = auth[len("Bearer "):] if auth.lower().startswith("bearer ") else ""
        if not provided or not hmac.compare_digest(secret, provided):
            logger.warning("Rejecting Google Chat webhook: missing/invalid bearer secret")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            event = await adapter.handle_inbound(payload)
            await _dispatch_event(adapter, event)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"Google Chat webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

    return [web.post("/webhook/google_chat", google_chat_webhook)]


def _feishu_route() -> list:
    """Feishu (Lark) event subscription — ``POST /webhook/feishu``.

    * URL verification: body ``type == "url_verification"`` — the body ``token``
      must match the verification token; the ``challenge`` is echoed back.
    * Signed events: headers ``X-Lark-Request-Timestamp`` /
      ``X-Lark-Request-Nonce`` / ``X-Lark-Signature`` verified with
      :meth:`FeishuAdapter.verify_callback`.
    """
    adapter = _adapter("feishu")
    if adapter is None:
        return []
    token = getattr(adapter, "verification_token", "")
    if not token:
        return []
    if not (hasattr(adapter, "verify_callback") and hasattr(adapter, "handle_webhook_payload")):
        return []

    async def feishu_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            logger.error(f"Feishu webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

        if payload.get("type") == "url_verification":
            if "challenge" not in payload:
                return web.Response(status=400, text="Bad request")
            body_token = payload.get("token", "")
            if not body_token or not hmac.compare_digest(token, body_token):
                logger.warning("Rejecting Feishu URL verification: token mismatch")
                return web.Response(status=401, text="Unauthorized")
            return web.Response(text=str(payload["challenge"]))

        ts = request.headers.get("X-Lark-Request-Timestamp", "")
        nonce = request.headers.get("X-Lark-Request-Nonce", "")
        signature = request.headers.get("X-Lark-Signature", "")
        if not (ts and nonce and signature) or not adapter.verify_callback(token, ts, nonce, signature):
            logger.warning("Rejecting Feishu webhook: missing/invalid X-Lark-Signature")
            return web.Response(status=401, text="Unauthorized")
        try:
            await adapter.handle_webhook_payload(payload)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"Feishu webhook handler error: {e}")
            return web.Response(status=500, text="Handler error")

    return [web.post("/webhook/feishu", feishu_webhook)]


def _yuanbao_route() -> list:
    """YuanBao — ``POST /webhook/yuanbao``.

    Signature: ``X-YuanBao-Signature`` = base64(HMAC-SHA256(
    ``YUANBAO_WEBHOOK_SECRET``, timestamp + nonce + secret)). Timestamp/nonce are
    read from the query string (platform default) or the equivalent headers.
    """
    adapter = _adapter("yuanbao")
    if adapter is None or not getattr(adapter, "webhook_secret", ""):
        return []
    if not hasattr(adapter, "verify_callback"):
        return []

    async def yuanbao_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        timestamp = request.query.get("timestamp", "") or request.headers.get("X-YuanBao-Timestamp", "")
        nonce = request.query.get("nonce", "") or request.headers.get("X-YuanBao-Nonce", "")
        signature = (request.headers.get("X-YuanBao-Signature", "")
                     or request.query.get("signature", ""))
        if not (timestamp and nonce) or not adapter.verify_callback(timestamp, nonce, signature):
            logger.warning("Rejecting YuanBao webhook: missing/invalid X-YuanBao-Signature")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            await adapter.handle_webhook_payload(payload)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"YuanBao webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

    return [web.post("/webhook/yuanbao", yuanbao_webhook)]


def _qqbot_route() -> list:
    """QQBot — ``POST /webhook/qqbot``.

    Signature: ``X-Signature`` = base64(HMAC-SHA256(QQBOT_SECRET, raw body)).
    A ``{"challenge": ...}`` payload is a URL-verification handshake and the
    challenge is echoed back after signature validation.
    """
    adapter = _adapter("qqbot")
    if adapter is None or not getattr(adapter, "secret", ""):
        return []
    if not (hasattr(adapter, "verify_callback") and hasattr(adapter, "parse_event")):
        return []

    async def qqbot_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        signature = request.headers.get("X-Signature", "")
        if not signature or not adapter.verify_callback(adapter.secret, raw, signature):
            logger.warning("Rejecting QQBot webhook: missing/invalid X-Signature")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            logger.error(f"QQBot webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")
        challenge, _ = adapter.parse_event(payload)
        if challenge is not None:
            return web.Response(text=str(challenge))
        try:
            await adapter.handle_webhook_payload(payload)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"QQBot webhook handler error: {e}")
            return web.Response(status=500, text="Handler error")

    return [web.post("/webhook/qqbot", qqbot_webhook)]


def _dingtalk_route() -> list:
    """DingTalk robot — ``POST /webhook/dingtalk``.

    Signature: DingTalk "加签" query params ``timestamp`` + ``sign`` verified with
    :meth:`DingtalkAdapter.verify_inbound_signature`. A ``check_url`` /
    ``check`` challenge payload echoes its ``challenge`` back; real message
    callbacks expect an empty 200 response.
    """
    adapter = _adapter("dingtalk")
    if adapter is None or not getattr(adapter, "webhook_secret", ""):
        return []
    if not hasattr(adapter, "verify_inbound_signature"):
        return []

    async def dingtalk_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        timestamp = request.query.get("timestamp", "") or request.headers.get("timestamp", "")
        sign = request.query.get("sign", "")
        if not adapter.verify_inbound_signature(adapter.webhook_secret, timestamp, sign):
            logger.warning("Rejecting DingTalk webhook: missing/invalid sign")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            logger.error(f"DingTalk webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")
        if payload.get("type") in ("check_url", "check") and isinstance(payload.get("challenge"), str):
            return web.Response(text=payload["challenge"])
        try:
            await adapter.handle_webhook_payload(payload)
            # DingTalk expects an empty body for accepted callbacks.
            return web.Response(status=200, text="")
        except Exception as e:
            logger.error(f"DingTalk webhook handler error: {e}")
            return web.Response(status=500, text="Handler error")

    return [web.post("/webhook/dingtalk", dingtalk_webhook)]


def _wecom_route() -> list:
    """WeCom (WeChat Work) app callback — ``GET/POST /webhook/wecom``.

    * URL verification (GET): ``msg_signature`` over sorted (token, timestamp,
      nonce, echostr); a match echoes ``echostr``.
    * Encrypted callback (POST): signed ``Encrypt`` payload verified with
      :meth:`WeComAdapter.verify_signature`, decrypted with
      :meth:`WeComAdapter.decrypt_message`, parsed with
      :meth:`WeComAdapter.parse_incoming`.
    """
    adapter = _adapter("wecom")
    if adapter is None:
        return []
    token = getattr(adapter, "token", "")
    aes_key = getattr(adapter, "encoding_aes_key", "")
    if not (token and aes_key):
        return []
    if not hasattr(adapter, "parse_incoming"):
        return []

    async def wecom_verify(request: web.Request) -> web.Response:
        ts = request.query.get("timestamp", "")
        nonce = request.query.get("nonce", "")
        echostr = request.query.get("echostr", "")
        msg_sig = request.query.get("msg_signature", "")
        if not adapter.verify_url(token, ts, nonce, echostr, msg_sig):
            logger.warning("Rejecting WeCom URL verification: signature mismatch")
            return web.Response(status=401, text="Unauthorized")
        return web.Response(text=echostr)

    async def wecom_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            logger.error(f"WeCom webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")
        msg_sig = data.get("MsgSignature", "")
        ts = data.get("TimeStamp", "")
        nonce = data.get("Nonce", "")
        encrypt = data.get("Encrypt", "")
        if not adapter.verify_signature(token, ts, nonce, encrypt, msg_sig):
            logger.warning("Rejecting WeCom webhook: missing/invalid MsgSignature")
            return web.Response(status=401, text="Unauthorized")
        xml_text = adapter.decrypt_message(aes_key, encrypt)
        if xml_text is None:
            logger.error("WeCom callback decryption failed")
            return web.Response(status=500, text="Decrypt failed")
        event = adapter.parse_incoming(xml_text)
        await _dispatch_event(adapter, event)
        # WeCom requires "success" (or empty) to stop retries.
        return web.Response(status=200, text="success")

    return [web.get("/webhook/wecom", wecom_verify), web.post("/webhook/wecom", wecom_webhook)]


def _weixin_route() -> list:
    """Weixin (WeChat Official Account) callback — ``GET/POST /webhook/weixin``.

    * URL verification (GET): ``signature`` over sorted (token, timestamp,
      nonce, echostr); a match echoes ``echostr``.
    * Plaintext callback (POST): raw XML body, ``signature`` over sorted
      (token, timestamp, nonce), parsed with :meth:`WeixinAdapter.parse_incoming`.
    * Encrypted callback (POST): JSON ``Encrypt`` payload verified over sorted
      (token, timestamp, nonce, encrypt) and decrypted with
      :meth:`WeixinAdapter.decrypt_message`.
    """
    adapter = _adapter("weixin")
    if adapter is None or not getattr(adapter, "token", ""):
        return []
    if not hasattr(adapter, "parse_incoming"):
        return []

    async def weixin_verify(request: web.Request) -> web.Response:
        ts = request.query.get("timestamp", "")
        nonce = request.query.get("nonce", "")
        echostr = request.query.get("echostr", "")
        signature = request.query.get("signature", "")
        if not adapter.verify_url(adapter.token, ts, nonce, echostr, signature):
            logger.warning("Rejecting Weixin URL verification: signature mismatch")
            return web.Response(status=401, text="Unauthorized")
        return web.Response(text=echostr)

    async def weixin_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        ts = request.query.get("timestamp", "")
        nonce = request.query.get("nonce", "")
        signature = request.query.get("signature", "")
        if not (ts and nonce):
            logger.warning("Rejecting Weixin webhook: missing timestamp/nonce")
            return web.Response(status=401, text="Unauthorized")
        body_text = raw.decode("utf-8", errors="replace") if raw else ""
        event = None
        if body_text.lstrip().startswith("<"):
            # Plaintext (raw XML) mode.
            if not signature or not adapter.verify_signature(adapter.token, ts, nonce, signature):
                logger.warning("Rejecting Weixin webhook: missing/invalid signature")
                return web.Response(status=401, text="Unauthorized")
            try:
                event = adapter.parse_incoming(body_text)
            except Exception as e:
                logger.error(f"Weixin webhook parse error: {e}")
                return web.Response(status=400, text="Bad request")
        else:
            # Encrypted (JSON) mode.
            try:
                data = json.loads(body_text) if body_text else {}
            except Exception as e:
                logger.error(f"Weixin webhook parse error: {e}")
                return web.Response(status=400, text="Bad request")
            aes_key = getattr(adapter, "encoding_aes_key", "")
            if not aes_key:
                return web.Response(status=500, text="Decrypt unavailable")
            encrypt = data.get("Encrypt", "")
            msg_sig = data.get("MsgSignature", "") or signature
            if not adapter.verify_url(adapter.token, ts, nonce, encrypt, msg_sig):
                logger.warning("Rejecting Weixin webhook: missing/invalid MsgSignature")
                return web.Response(status=401, text="Unauthorized")
            xml_text = adapter.decrypt_message(aes_key, encrypt) if aes_key else None
            if xml_text is None:
                return web.Response(status=500, text="Decrypt failed")
            event = adapter.parse_incoming(xml_text)
        await _dispatch_event(adapter, event)
        # WeChat expects an empty body on success to avoid retries.
        return web.Response(status=200, text="")

    return [web.get("/webhook/weixin", weixin_verify), web.post("/webhook/weixin", weixin_webhook)]


def _bluebubbles_route() -> list:
    """BlueBubbles (iMessage) — ``POST /webhook/bluebubbles``.

    BlueBubbles does not sign its forwarded webhooks; operators enable inbound
    by configuring ``BLUEBUBBLES_WEBHOOK_SECRET`` and having the BlueBubbles
    server send it in the ``X-Webhook-Secret`` header. ``handle_inbound``
    normalises the payload; the resulting :class:`MessageEvent` is dispatched
    by the route.
    """
    adapter = _adapter("bluebubbles")
    if adapter is None:
        return []
    secret = os.getenv("BLUEBUBBLES_WEBHOOK_SECRET", "")
    if not secret:
        return []
    if not hasattr(adapter, "handle_inbound"):
        return []

    async def bluebubbles_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        provided = request.headers.get(HEADER_WEBHOOK_SECRET, "")
        if not provided or not hmac.compare_digest(secret, provided):
            logger.warning("Rejecting BlueBubbles webhook: missing/invalid X-Webhook-Secret")
            return web.Response(status=401, text="Unauthorized")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            event = await adapter.handle_inbound(payload)
            await _dispatch_event(adapter, event)
            return web.Response(status=200, text="EVENT_RECEIVED")
        except Exception as e:
            logger.error(f"BlueBubbles webhook parse error: {e}")
            return web.Response(status=400, text="Bad request")

    return [web.post("/webhook/bluebubbles", bluebubbles_webhook)]


def build_platform_routes() -> List[web.AbstractRoute]:
    """Return the inbound routes for every platform whose credentials are set.

    A platform's routes are only included when both:
      * the adapter instance is present in the ``_adapters`` registry, and
      * the platform's verification secret / token is configured.

    Platforms without credentials expose no HTTP surface (404), matching the
    Meta path's env-gated behaviour.
    """
    built: List[web.AbstractRoute] = []
    for builder in (
        _line_route,
        _teams_route,
        _google_chat_route,
        _feishu_route,
        _yuanbao_route,
        _qqbot_route,
        _dingtalk_route,
        _wecom_route,
        _weixin_route,
        _bluebubbles_route,
    ):
        built.extend(builder())
    return built


async def start_webhook_server(
    adapters: Dict[str, object],
    verify_token: str = "",
    app_secret: str = "",
    host: str = "0.0.0.0",
    port: int = 8080,
):
    """
    Start the webhook HTTP server.

    Args:
        adapters: Dict mapping platform name -> adapter instance. The full set
            is used so that every configured platform's inbound route is added.
        verify_token: Meta webhook verification token
        app_secret: Meta app secret for X-Hub-Signature-256 verification.
            Falls back to the META_APP_SECRET / WHATSAPP_APP_SECRET env vars.
        host: Bind address
        port: Listen port
    """
    global _adapters, _verify_token, _app_secret
    _adapters = adapters
    _verify_token = verify_token
    _app_secret = (
        app_secret
        or os.getenv("META_APP_SECRET", "")
        or os.getenv("WHATSAPP_APP_SECRET", "")
    )

    app = web.Application()
    app.add_routes(routes)
    app.add_routes(build_platform_routes())

    logger.info(f"NEXUS webhook server listening on {host}:{port}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Keep running
    while True:
        await asyncio.sleep(3600)
