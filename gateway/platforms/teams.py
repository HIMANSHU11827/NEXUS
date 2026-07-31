"""Microsoft Teams gateway adapter for NEXUS.

Two outbound modes are supported, selected automatically from the environment:

* **Incoming webhook connector** (``TEAMS_WEBHOOK_URL``): the simplest option.
  NEXUS POSTs a JSON message to a channel-specific Office 365 connector URL. No
  Azure AD app registration required.
* **Microsoft Graph** (``TEAMS_TENANT_ID`` + ``TEAMS_CLIENT_ID`` +
  ``TEAMS_CLIENT_SECRET`` + optional ``TEAMS_TEAM_ID`` / ``TEAMS_CHANNEL_ID``):
  sends messages via the Graph ``/teams/{team}/channels/{channel}/messages``
  endpoint using an OAuth2 client-credentials bearer token.

Inbound messages arrive through the Bot Framework activity protocol. The adapter
exposes ``handle_webhook_payload`` so the NEXUS webhook server can route
``/webhook/teams`` POSTs into normalised :class:`~gateway.base.MessageEvent`
objects without any live network access (the parser is a pure function, fully
unit-testable).

The adapter is **env-gated**: ``connect()`` returns ``False`` unless a webhook
URL *or* a full Graph credential set is present, and the gateway only registers
it when the relevant env vars exist. The only hard dependency is ``httpx``
(already a project requirement); the optional ``msal`` library is *not* required
because token acquisition is done with a direct ``httpx`` call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import List, Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

# Optional helper library — not required; token fetch is done with httpx.
try:  # pragma: no cover - optional
    import msal  # type: ignore
    HAS_MSAL = True
except Exception:  # pragma: no cover - optional dependency absent
    msal = None  # type: ignore
    HAS_MSAL = False

TEAMS_WEBHOOK_MODE = "webhook"
TEAMS_GRAPH_MODE = "graph"

# Env vars that, when any is present, mean the Teams gateway is "interesting"
# enough to register. ``connect()`` performs the real validation.
TEAMS_REQUIRED_ENV = (
    "TEAMS_WEBHOOK_URL",
    "TEAMS_CLIENT_ID",
    "TEAMS_BOT_TOKEN",
)


class TeamsAdapter(BasePlatformAdapter):
    """NEXUS Microsoft Teams Adapter (webhook or Graph API)."""

    name = "teams"
    required_env = TEAMS_REQUIRED_ENV

    def __init__(
        self,
        webhook_url: str = "",
        client_id: str = "",
        client_secret: str = "",
        tenant_id: str = "",
        team_id: str = "",
        channel_id: str = "",
        bot_token: str = "",
    ):
        super().__init__("teams")
        self.webhook_url = webhook_url or os.getenv("TEAMS_WEBHOOK_URL", "")
        self.client_id = client_id or os.getenv("TEAMS_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("TEAMS_CLIENT_SECRET", "")
        self.tenant_id = tenant_id or os.getenv("TEAMS_TENANT_ID", "")
        self.team_id = team_id or os.getenv("TEAMS_TEAM_ID", "")
        self.channel_id = channel_id or os.getenv("TEAMS_CHANNEL_ID", "")
        self.bot_token = bot_token or os.getenv("TEAMS_BOT_TOKEN", "")

        if self.webhook_url:
            self.mode = TEAMS_WEBHOOK_MODE
        elif self.client_id and self.client_secret and self.tenant_id:
            self.mode = TEAMS_GRAPH_MODE
        else:
            self.mode = None

        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # -- env-gating --------------------------------------------------------
    def is_configured(self) -> bool:
        return self.mode is not None

    # -- connection lifecycle --------------------------------------------
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "Teams adapter unavailable: set TEAMS_WEBHOOK_URL or "
                "(TEAMS_TENANT_ID + TEAMS_CLIENT_ID + TEAMS_CLIENT_SECRET)"
            )
            return False
        try:
            self._client = httpx.AsyncClient(timeout=30.0)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Teams connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None

    # -- outbound ----------------------------------------------------------
    @staticmethod
    def _build_webhook_payload(text: str, reply_to: Optional[str] = None) -> dict:
        """Office 365 connector message payload."""
        payload: dict = {"text": text}
        if reply_to:
            payload["summary"] = f"reply to {reply_to}"
        return payload

    @staticmethod
    def _build_graph_payload(text: str, reply_to: Optional[str] = None) -> dict:
        payload: dict = {"body": {"contentType": "text", "content": text}}
        if reply_to:
            payload["replyToId"] = reply_to
        return payload

    async def _get_access_token(self) -> Optional[str]:
        """Return a cached OAuth2 client-credentials token for Graph, or None."""
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        if not (self.tenant_id and self.client_id and self.client_secret):
            return None
        try:
            token_url = (
                f"https://login.microsoftonline.com/{self.tenant_id}"
                "/oauth2/v2.0/token"
            )
            resp = await self._client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                logger.error(f"Teams token request failed: {resp.status_code}")
                return None
            data = resp.json()
            self._token = data.get("access_token")
            self._token_expiry = time.time() + float(data.get("expires_in", 3600))
            return self._token
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"Teams token request error: {e}")
            return None

    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")

        try:
            if self.mode == TEAMS_WEBHOOK_MODE:
                resp = await self._client.post(
                    self.webhook_url, json=self._build_webhook_payload(text, reply_to)
                )
                ok = resp.status_code in (200, 201, 202)
                return SendResult(
                    success=ok,
                    error=None if ok else f"HTTP {resp.status_code}",
                )

            # Graph mode
            token = await self._get_access_token()
            if not token:
                return SendResult(success=False, error="Could not obtain Graph token")
            channel = chat_id or self.channel_id
            if not (self.team_id and channel):
                return SendResult(
                    success=False,
                    error="TEAMS_TEAM_ID and a channel id are required for Graph send",
                )
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            if reply_to:
                url = (
                    f"https://graph.microsoft.com/v1.0/teams/{self.team_id}"
                    f"/channels/{channel}/messages/{reply_to}/replies"
                )
            else:
                url = (
                    f"https://graph.microsoft.com/v1.0/teams/{self.team_id}"
                    f"/channels/{channel}/messages"
                )
            resp = await self._client.post(
                url, headers=headers, json=self._build_graph_payload(text)
            )
            ok = resp.status_code in (200, 201)
            data = resp.json() if resp.content else {}
            return SendResult(
                success=ok,
                message_id=data.get("id"),
                error=None if ok else f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(
        self, chat_id: str, image_url: str, caption: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        body = f"{caption}\n{image_url}" if caption else image_url
        # Teams incoming webhooks / Graph chat messages can't trivially embed
        # raw image bytes without an upload session, so we send the URL.
        return await self.send_text(chat_id, body)

    async def send_typing(self, chat_id: str):
        # Teams webhooks have no typing indicator; Graph typing is channel-scoped
        # and not essential. No-op, intentionally safe.
        pass

    # -- inbound -----------------------------------------------------------
    @staticmethod
    def _parse_teams_activity(activity: dict) -> Optional[MessageEvent]:
        """Parse a Bot Framework *activity* dict into a MessageEvent.

        Returns ``None`` for non-message activities (typing, conversationUpdate,
        reactions) or payloads without the minimum sender/conversation data.
        Pure / synchronous so it can be unit tested without a network.
        """
        if not isinstance(activity, dict):
            return None
        if activity.get("type") != "message":
            return None
        text = (activity.get("text") or "").strip()
        if not text:
            return None

        sender = activity.get("from", {}) or {}
        sender_id = sender.get("id", "") if isinstance(sender, dict) else ""
        conversation = activity.get("conversation", {}) or {}
        chat_id = conversation.get("id", "") if isinstance(conversation, dict) else ""
        message_id = activity.get("id", "")
        if not (sender_id and chat_id):
            return None

        return MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="teams",
            message_type="text",
            message_id=message_id,
            raw_data=activity,
        )

    async def handle_webhook_payload(self, activity: dict):
        """Receive a Bot Framework activity from the webhook server.

        The activity may be wrapped in a ``{"value": [...]}`` or
        ``{"activities": [...]}`` envelope (Bot Framework sometimes batches),
        in which case every contained activity is processed.
        """
        if not self._on_message:
            return

        activities: List[dict] = []
        if isinstance(activity, dict):
            if "activities" in activity and isinstance(activity["activities"], list):
                activities = activity["activities"]
            elif "value" in activity and isinstance(activity["value"], list):
                activities = activity["value"]
            else:
                activities = [activity]
        elif isinstance(activity, list):
            activities = activity

        for item in activities:
            event = self._parse_teams_activity(item)
            if event is not None:
                result = self._on_message(event)
                if asyncio.iscoroutine(result):
                    await result
