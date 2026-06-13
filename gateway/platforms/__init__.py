"""Gateway platform adapters.

Adapters are imported from their concrete modules so optional platform
dependencies are only loaded when that gateway is enabled.
"""

__all__ = [
    "DiscordAdapter",
    "MetaAdapter",
    "TelegramAdapter",
    "WhatsAppAdapter",
]
