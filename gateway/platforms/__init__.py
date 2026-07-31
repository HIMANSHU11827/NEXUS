"""Gateway platform adapters.

Adapters are imported from their concrete modules so optional platform
dependencies are only loaded when that gateway is enabled.

The ``get_adapter`` factory returns an adapter instance from env config.
"""

from importlib import import_module

__all__ = [
    "DiscordAdapter",
    "EmailAdapter",
    "IRCAdapter",
    "LineAdapter",
    "MattermostAdapter",
    "MatrixAdapter",
    "MetaAdapter",
    "SMSAdapter",
    "SignalAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    "WhatsAppAdapter",
    "TeamsAdapter",
    "GoogleChatAdapter",
    "WeComAdapter",
    "FeishuAdapter",
]

_ADAPTER_MAP = {
    "telegram": ("gateway.platforms.telegram", "TelegramAdapter"),
    "discord": ("gateway.platforms.discord", "DiscordAdapter"),
    "whatsapp": ("gateway.platforms.whatsapp", "WhatsAppAdapter"),
    "meta": ("gateway.platforms.meta", "MetaAdapter"),
    "slack": ("gateway.platforms.slack", "SlackAdapter"),
    "signal": ("gateway.platforms.signal", "SignalAdapter"),
    "matrix": ("gateway.platforms.matrix", "MatrixAdapter"),
    "mattermost": ("gateway.platforms.mattermost", "MattermostAdapter"),
    "email": ("gateway.platforms.email", "EmailAdapter"),
    "sms": ("gateway.platforms.sms", "SMSAdapter"),
    "irc": ("gateway.platforms.irc", "IRCAdapter"),
    "line": ("gateway.platforms.line", "LineAdapter"),
    "teams": ("gateway.platforms.teams", "TeamsAdapter"),
    "google_chat": ("gateway.platforms.google_chat", "GoogleChatAdapter"),
    "wecom": ("gateway.platforms.wecom", "WeComAdapter"),
    "feishu": ("gateway.platforms.feishu", "FeishuAdapter"),
}

_CLASS_TO_PLATFORM = {class_name: platform for platform, (_module, class_name) in _ADAPTER_MAP.items()}


def _load_adapter_class(platform: str):
    spec = _ADAPTER_MAP.get(platform)
    if spec is None:
        raise ValueError(f"Unknown platform: {platform!r}")
    module_name, class_name = spec
    module = import_module(module_name)
    return getattr(module, class_name)


def __getattr__(name: str):
    platform = _CLASS_TO_PLATFORM.get(name)
    if platform is None:
        raise AttributeError(name)
    return _load_adapter_class(platform)


def get_adapter(platform: str, **kwargs):
    """Return an adapter instance for *platform* by name.

    Extra keyword arguments are forwarded to the adapter constructor.
    """
    cls = _load_adapter_class(platform)
    return cls(**kwargs)


def all_adapters():
    """Return a list of adapter names that can be registered."""
    return list(_ADAPTER_MAP.keys())
