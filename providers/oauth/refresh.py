import time
from typing import Optional

from providers.oauth.registry import get_oauth_provider
from providers.oauth.storage import OAuthTokenStore, load_oauth_token_store
from providers.oauth.types import OAuthCredentials


async def refresh_oauth_token(
    provider_id: str,
    credentials: OAuthCredentials,
    store: OAuthTokenStore,
    force: bool = False,
) -> Optional[OAuthCredentials]:
    now_ms = time.time() * 1000
    if not force and now_ms < credentials.expires:
        return credentials

    provider = get_oauth_provider(provider_id)
    if provider is None:
        return None

    try:
        refreshed = await provider.refresh_token(credentials)
        store.set(provider_id, refreshed)
        return refreshed
    except Exception:
        return None


async def ensure_valid_oauth_credentials(
    provider_id: str,
    store: Optional[OAuthTokenStore] = None,
) -> Optional[OAuthCredentials]:
    store = store or load_oauth_token_store()
    credentials = store.get(provider_id)
    if credentials is None:
        return None

    return await refresh_oauth_token(provider_id, credentials, store)
