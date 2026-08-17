import asyncio

from models.providers.auth.oauth.storage import get_oauth_api_key
from models.providers.auth.oauth.types import OAuthCredentials


class _Store:
    def __init__(self):
        self.credentials = OAuthCredentials("old", "refresh", 1.0)
        self.saved = []

    def get(self, _provider_id):
        return self.credentials

    def set(self, _provider_id, credentials):
        self.credentials = credentials
        self.saved.append(credentials)


def test_async_expired_refresh_is_single_flight(monkeypatch):
    store = _Store()
    calls = {"count": 0}

    class Provider:
        async def refresh_token(self, credentials):
            calls["count"] += 1
            await asyncio.sleep(0)
            return OAuthCredentials("fresh", credentials.refresh, 9_999_999_999_999.0)

        @staticmethod
        def get_api_key(credentials):
            return credentials.access

    monkeypatch.setattr("models.providers.auth.oauth.registry.get_oauth_provider", lambda _id: Provider())

    async def run():
        return await asyncio.gather(
            get_oauth_api_key("singleflight", store),
            get_oauth_api_key("singleflight", store),
        )

    assert asyncio.run(run()) == ["fresh", "fresh"]
    assert calls["count"] == 1
    assert len(store.saved) == 1
