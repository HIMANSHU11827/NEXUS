from typing import Optional

from providers.oauth.types import OAuthProviderInterface

_oauth_registry: dict[str, OAuthProviderInterface] = {}


def register_oauth_provider(provider: OAuthProviderInterface) -> None:
    _oauth_registry[provider.id] = provider


def get_oauth_provider(provider_id: str) -> Optional[OAuthProviderInterface]:
    return _oauth_registry.get(provider_id)


def get_oauth_providers() -> list[OAuthProviderInterface]:
    return list(_oauth_registry.values())


def reset_oauth_providers() -> None:
    _oauth_registry.clear()


OAuthProviderRegistry = _oauth_registry
