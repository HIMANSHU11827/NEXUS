"""WhatsApp gateway adapter backed by Meta Graph messaging."""

import logging
import os

from gateway.platforms.meta import MetaAdapter

logger = logging.getLogger(__name__)


class WhatsAppAdapter(MetaAdapter):
    """NEXUS WhatsApp adapter using the shared Meta gateway transport.

    Inherits all send/webhook behaviour from :class:`MetaAdapter` and simply
    pins the platform to ``whatsapp``. Credentials are resolved from
    ``META_ACCESS_TOKEN`` / ``META_PAGE_TOKEN`` / ``WHATSAPP_TOKEN`` and the
    sender phone-number-id from ``META_PHONE_NUMBER_ID`` / ``WHATSAPP_PHONE_ID``.
    """

    required_env = ("META_ACCESS_TOKEN", "META_PAGE_TOKEN", "WHATSAPP_TOKEN")

    def __init__(self, access_token: str = "", verify_token: str = "", phone_number_id: str = ""):
        super().__init__("whatsapp", access_token, verify_token)
        # Allow explicit phone-number-id injection (used by tests / config).
        self._phone_id = phone_number_id or os.getenv("META_PHONE_NUMBER_ID", "") or os.getenv(
            "WHATSAPP_PHONE_ID", ""
        )

    def _phone_number_id(self, chat_id: str) -> str:
        return (self._phone_id or super()._phone_number_id(chat_id)).strip()

    def is_configured(self) -> bool:
        """WhatsApp requires both a token and a phone-number-id to send."""
        return bool(self.access_token) and bool(self._phone_number_id(""))
