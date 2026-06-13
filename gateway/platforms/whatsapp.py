"""WhatsApp gateway adapter backed by Meta Graph messaging."""

from gateway.platforms.meta import MetaAdapter


class WhatsAppAdapter(MetaAdapter):
    """NEXUS WhatsApp adapter using the shared Meta gateway transport."""

    def __init__(self, access_token: str, verify_token: str = ""):
        super().__init__("whatsapp", access_token, verify_token)
