"""NEXUS unified external communications gateway."""

from gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.platforms import all_adapters, get_adapter
from gateway.run import GatewayRunner
from gateway.supervisor import GatewaySupervisor, PlatformRuntime

# Every adapter class exported by ``gateway.platforms`` must also be
# importable from the ``gateway`` package itself, so callers can rely on a
# single public import surface regardless of platform family. Kept in sync
# with ``gateway/platforms/__init__.py`` (audit P23).
_PLATFORM_ADAPTER_NAMES = (
    "BlueBubblesAdapter",
    "DingtalkAdapter",
    "DiscordAdapter",
    "EmailAdapter",
    "FeishuAdapter",
    "GoogleChatAdapter",
    "IRCAdapter",
    "LineAdapter",
    "MattermostAdapter",
    "MatrixAdapter",
    "MetaAdapter",
    "QQBotAdapter",
    "SMSAdapter",
    "SignalAdapter",
    "SlackAdapter",
    "TeamsAdapter",
    "TelegramAdapter",
    "WeComAdapter",
    "WeixinAdapter",
    "WhatsAppAdapter",
    "YuanbaoAdapter",
)

__all__ = [
    "BasePlatformAdapter",
    "GatewayRunner",
    "GatewaySupervisor",
    "MessageEvent",
    "MessageType",
    "PlatformRuntime",
    "SendResult",
    "get_adapter",
    "all_adapters",
    *_PLATFORM_ADAPTER_NAMES,
]

_LAZY_PLATFORM_EXPORTS = set(_PLATFORM_ADAPTER_NAMES)


def __getattr__(name: str):
    if name not in _LAZY_PLATFORM_EXPORTS:
        raise AttributeError(name)
    from gateway import platforms

    return getattr(platforms, name)
