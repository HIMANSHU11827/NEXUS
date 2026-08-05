import asyncio
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional

from gateway.base import BasePlatformAdapter, MessageEvent
from gateway.platforms import all_adapters, get_adapter
from gateway.session_ids import gateway_session_id
from orchestrators import NexusLoop
from providers.reliability import bounded_tool_retry

logger = logging.getLogger(__name__)


class IngressDedupe:
    """Size- and TTL-bounded LRU of recently seen ingress keys.

    ``seen(key)`` records the key and returns True when it was already seen
    within the TTL (i.e. a duplicate delivery), False when it is new. Bounded
    to ``max_size`` entries (default 10_000) and ``ttl`` seconds (default
    10 minutes) so a webhook retry storm never double-processes a message and
    memory never grows without bound. Thread-safe.
    """

    DEFAULT_MAX_SIZE = 10_000
    DEFAULT_TTL = 600.0

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ttl: float = DEFAULT_TTL) -> None:
        self.max_size = int(max_size)
        self.ttl = float(ttl)
        self._recent: "OrderedDict[str, float]" = OrderedDict()
        self._lock = threading.Lock()

    def seen(self, key: str, now: Optional[float] = None) -> bool:
        """Return True when ``key`` was seen within the TTL (duplicate).

        Otherwise records the key (moving it to the most-recent end) and
        returns False — callers should only process brand-new keys.
        """
        if not key:
            return False
        if now is None:
            now = time.time()
        with self._lock:
            stamp = self._recent.pop(key, None)
            if stamp is not None and (now - stamp) < self.ttl:
                self._recent[key] = stamp  # touch -> most-recent end
                return True
            self._recent[key] = now
            while len(self._recent) > self.max_size:
                self._recent.popitem(last=False)
            return False

    def clear(self) -> None:
        with self._lock:
            self._recent.clear()


ingress_dedupe = IngressDedupe()


def dedupe_key_for_event(event: MessageEvent) -> str:
    """Build a stable ingress key for an event.

    Prefers ``event.message_id`` when present; otherwise falls back to a hash
    of (platform, chat, text, timestamp) so platforms that do not surface a
    message id still get reliable de-duplication.
    """
    platform = str(getattr(event, "platform", "") or "")
    message_id = getattr(event, "message_id", None)
    if message_id:
        return f"{platform}:msg:{message_id}"
    chat = str(getattr(event, "chat_id", "") or "")
    text = str(getattr(event, "text", "") or "")
    timestamp = str(getattr(event, "timestamp", "") or "")
    digest = hashlib.sha256(f"{platform}|{chat}|{text}|{timestamp}".encode("utf-8")).hexdigest()
    return f"{platform}:hash:{digest}"


def seen_event(event: MessageEvent) -> bool:
    """Return True when this event is a duplicate we have already handled.

    Events that already passed through an outer ingress layer are marked via
    :func:`mark_handled` so the gateway handler does not double-count the very
    same delivery (a webhook event routed straight into ``handle_message``).
    """
    if getattr(event, "_ingress_seen", False):
        return False
    return ingress_dedupe.seen(dedupe_key_for_event(event))


def mark_handled(event: MessageEvent) -> None:
    """Mark an event as counted by an outer ingress layer."""
    try:
        event._ingress_seen = True  # type: ignore[attr-defined]
    except Exception:  # degrade softly
        logger.debug("could not mark event as deduped", exc_info=True)


_PLATFORM_ENV_MAP: Dict[str, List[List[str]]] = {
    "telegram": [["TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"]],
    "discord": [["DISCORD_BOT_TOKEN", "DISCORD_TOKEN"]],
    "whatsapp": [["META_ACCESS_TOKEN", "WHATSAPP_TOKEN"], ["META_PHONE_NUMBER_ID", "WHATSAPP_PHONE_ID"]],
    "meta": [["META_ACCESS_TOKEN", "META_PAGE_TOKEN"]],
    "slack": [["SLACK_BOT_TOKEN", "SLACK_TOKEN"]],
    "signal": [["SIGNAL_NUMBER"]],
    "matrix": [["MATRIX_HOMESERVER"], ["MATRIX_USER"]],
    "mattermost": [["MATTERMOST_URL"], ["MATTERMOST_TOKEN"]],
    "email": [["SMTP_HOST"], ["SMTP_USER"], ["SMTP_PASS"]],
    "sms": [["TWILIO_ACCOUNT_SID"], ["TWILIO_AUTH_TOKEN"], ["TWILIO_FROM_NUMBER"]],
    "irc": [["IRC_NICK"]],
    "line": [["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_TOKEN"]],
    "teams": [["TEAMS_WEBHOOK_URL"], ["TEAMS_TENANT_ID"], ["TEAMS_CLIENT_ID"]],
    "google_chat": [["GOOGLE_CHAT_WEBHOOK_URL"], ["GOOGLE_CHAT_SPACE", "GOOGLE_CHAT_KEY"]],
    "wecom": [["WECOM_WEBHOOK"], ["WECOM_CORPID", "WECOM_AGENTID", "WECOM_SECRET"]],
    "feishu": [["FEISHU_WEBHOOK"], ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]],
    "yuanbao": [["YUANBAO_ACCESS_TOKEN", "YUANBAO_TOKEN"]],
    "weixin": [["WX_APPID"], ["WX_APPSECRET"]],
    "qqbot": [["QQBOT_APPID"], ["QQBOT_SECRET"]],
    "dingtalk": [
        ["DINGTALK_WEBHOOK_ACCESS_TOKEN", "DINGTALK_ROBOT_TOKEN", "DINGTALK_WEBHOOK"],
        ["DINGTALK_APP_KEY", "DINGTALK_APP_SECRET"],
    ],
    "bluebubbles": [["BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"]],
}


def _has_required_env(required_groups: List[List[str]]) -> bool:
    return all(any(os.getenv(name) for name in group) for group in required_groups)


class GatewayRunner:
    """
    NEXUS UNIFIED GATEWAY COMMANDER
    Orchestrates platform adapters and routes them to the shared NexusLoop runtime.
    Each chat maps to a stable session id visible on TUI and GUI.
    """

    def __init__(self):
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._loops: Dict[str, NexusLoop] = {}
        self._running = False

    @staticmethod
    def session_id_for(event: MessageEvent) -> str:
        return gateway_session_id(event.platform, event.chat_id)

    def _get_loop(self, event: MessageEvent) -> NexusLoop:
        session_id = self.session_id_for(event)
        if session_id not in self._loops:
            loop = NexusLoop()
            loop.load_memory(session_id)
            self._loops[session_id] = loop
        return self._loops[session_id]

    def add_adapter(self, adapter: BasePlatformAdapter):
        self.adapters[adapter.platform] = adapter
        adapter.set_message_handler(self.handle_message)

    def register_all(self):
        """Auto-discover and register every platform whose env vars are present."""
        for platform_name in all_adapters():
            required = _PLATFORM_ENV_MAP.get(platform_name, [])
            if required and not _has_required_env(required):
                logger.debug(f"Skipping {platform_name} — missing env vars {required}")
                continue

            try:
                adapter = get_adapter(platform_name)
                self.add_adapter(adapter)
                logger.info(f"Registered {platform_name} adapter")
            except Exception as e:
                logger.warning(f"Failed to register {platform_name}: {e}")

    def is_authorized(self, event: MessageEvent) -> bool:
        """Check if the user is allowed to issue commands."""
        from authentication import is_gateway_authorized
        return is_gateway_authorized(event.platform, event.sender_id)

    async def handle_message(self, event: MessageEvent):
        """Route incoming message to NexusLoop and send response back."""
        if not self.is_authorized(event):
            logger.warning(f"Unauthorized access attempt from {event.platform}:{event.sender_id}")
            return

        adapter = self.adapters.get(event.platform)
        if not adapter:
            return

        # Ingress de-duplication: webhook retry storms or re-delivered platform
        # events must never double-process a message.
        try:
            if seen_event(event):
                logger.info(
                    "Dropping duplicate message from %s:%s (message_id=%s)",
                    event.platform, event.sender_id, event.message_id,
                )
                return
        except Exception:  # degrade softly — never drop on dedupe failure
            logger.debug("message dedupe check failed", exc_info=True)

        from utils.session_bus import set_active_session_id, sync_loop_from_disk

        session_id = self.session_id_for(event)
        logger.info(
            "Processing message from %s:%s (session=%s)",
            event.platform, event.sender_id, session_id,
        )

        # Send typing/action indicator (bounded retry for transient jitter)
        await bounded_tool_retry(adapter.send_typing, event.chat_id, retry_policy=2)

        try:
            loop = self._get_loop(event)
            set_active_session_id(loop.root, session_id, source=f"gateway:{event.platform}")
            sync_loop_from_disk(loop)
            response_buffer = ""
            async for chunk in loop.stream_run(event.text):
                if isinstance(chunk, dict):
                    if chunk.get("type") != "content":
                        continue
                    content = chunk.get("data")
                    if not isinstance(content, str):
                        continue
                elif isinstance(chunk, str):
                    content = chunk
                else:
                    continue

                if not content or content.startswith("[TOOL_") or content.startswith("[NEXUS_ACTIVITY]"):
                    continue
                response_buffer += content
                if len(response_buffer) > 2000:
                    await bounded_tool_retry(
                        adapter.send_text, event.chat_id, response_buffer, retry_policy=2
                    )
                    response_buffer = ""

            if response_buffer:
                await bounded_tool_retry(
                    adapter.send_text, event.chat_id, response_buffer, retry_policy=2
                )

        except Exception as e:
            logger.error(f"Error in gateway reasoning: {e}")
            await adapter.send_text(event.chat_id, f"❌ [GATEWAY_ERROR]: {str(e)}")

    async def run(self):
        """Start all added adapters."""
        self._running = True
        for adapter in self.adapters.values():
            success = await adapter.connect()
            if success:
                logger.info(f"Successfully connected {adapter.platform} adapter.")
            else:
                logger.error(f"Failed to connect {adapter.platform} adapter.")

        # Keep the loop alive
        while self._running:
            await asyncio.sleep(1)

    async def stop(self):
        self._running = False
        for adapter in self.adapters.values():
            await adapter.disconnect()
