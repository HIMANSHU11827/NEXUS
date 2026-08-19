import logging
import time
from typing import Optional

from models.providers.auth.oauth.expiry import OAUTH_REFRESH_SKEW_MS
from models.providers.auth.oauth.registry import get_oauth_provider
from models.providers.auth.oauth.storage import OAuthTokenStore, load_oauth_token_store
from models.providers.auth.oauth.types import OAuthCredentials

logger = logging.getLogger("nexus.oauth.refresh")


async def refresh_oauth_token(
    provider_id: str,
    credentials: OAuthCredentials,
    store: OAuthTokenStore,
    force: bool = False,
) -> Optional[OAuthCredentials]:
    now_ms = time.time() * 1000
    # Refresh before expiry (5-minute skew) so access never races an expiring token.
    if not force and (now_ms + OAUTH_REFRESH_SKEW_MS) < credentials.expires:
        return credentials

    provider = get_oauth_provider(provider_id)
    if provider is None:
        return None

    try:
        refreshed = await provider.refresh_token(credentials)
        store.set(provider_id, refreshed)
        return refreshed
    except Exception as exc:
        logger.warning("OAuth refresh failed for provider %s: %s", provider_id, exc)
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