"""NEXUS unified external communications gateway."""

from gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.platforms import all_adapters, get_adapter
from gateway.run import GatewayRunner
from gateway.supervisor import GatewaySupervisor, PlatformRuntime

__all__ = [
    "BasePlatformAdapter",
    "DiscordAdapter",
    "EmailAdapter",
    "GatewayRunner",
    "GatewaySupervisor",
    "MattermostAdapter",
    "MatrixAdapter",
    "MessageEvent",
    "MessageType",
    "MetaAdapter",
    "PlatformRuntime",
    "SMSAdapter",
    "SendResult",
    "SignalAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    "WhatsAppAdapter",
    "get_adapter",
    "all_adapters",
]

_LAZY_PLATFORM_EXPORTS = {
    "DiscordAdapter",
    "EmailAdapter",
    "MattermostAdapter",
    "MatrixAdapter",
    "MetaAdapter",
    "SMSAdapter",
    "SendResult",
    "SignalAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    "WhatsAppAdapter",
}


def __getattr__(name: str):
    if name not in _LAZY_PLATFORM_EXPORTS:
        raise AttributeError(name)
    from gateway import platforms

    return getattr(platforms, name)
