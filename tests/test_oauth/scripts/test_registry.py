from models.providers.auth.oauth.registry import (
    get_oauth_provider,
    get_oauth_providers,
    register_oauth_provider,
    reset_oauth_providers,
)
from models.providers.auth.oauth.types import OAuthCredentials


class FakeOAuthProvider:
    id = "fake"
    name = "Fake Provider"

    async def login(self, callbacks):
        return OAuthCredentials("a", "r", 999.0)

    async def refresh_token(self, credentials):
        return OAuthCredentials("a2", "r2", 1999.0)

    def get_api_key(self, credentials):
        return credentials.access


class TestOAuthRegistry:
    def setup_method(self):
        reset_oauth_providers()

    def test_register_and_get(self):
        register_oauth_provider(FakeOAuthProvider())
        provider = get_oauth_provider("fake")
        assert provider is not None
        assert provider.id == "fake"
        assert provider.name == "Fake Provider"

    def test_get_unknown_returns_none(self):
        assert get_oauth_provider("nonexistent") is None

    def test_get_oauth_providers_returns_all(self):
        register_oauth_provider(FakeOAuthProvider())
        providers = get_oauth_providers()
        assert any(p.id == "fake" for p in providers)

    def test_reset_clears_registry(self):
        register_oauth_provider(FakeOAuthProvider())
        reset_oauth_providers()
        assert get_oauth_provider("fake") is None
