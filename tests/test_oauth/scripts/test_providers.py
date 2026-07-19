import asyncio
import sys
from types import SimpleNamespace

from providers.oauth.providers.autoregister import register_all_oauth_providers
from providers.oauth.registry import get_oauth_providers, reset_oauth_providers
from providers.oauth.types import OAuthCredentials


class TestOAuthProviderRegistration:
    def setup_method(self):
        reset_oauth_providers()
        register_all_oauth_providers()

    def test_all_providers_registered(self):
        providers = get_oauth_providers()
        provider_ids = {p.id for p in providers}
        expected = {"codex", "claude", "github-copilot", "grok", "gemini", "openrouter", "minimax", "chutes", "qwen"}
        for eid in expected:
            assert eid in provider_ids, f"Missing OAuth provider: {eid}"

    def test_each_provider_has_get_api_key(self):
        for p in get_oauth_providers():
            creds = OAuthCredentials(access="test_key", refresh="test_refresh", expires=99999.0)
            key = p.get_api_key(creds)
            assert key == "test_key"

    def test_each_provider_has_id_and_name(self):
        for p in get_oauth_providers():
            assert p.id
            assert p.name


def test_openrouter_refresh_stores_absolute_expiry_ms(monkeypatch):
    from providers.oauth.providers import openrouter

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "a2", "refresh_token": "r2", "expires_in": 10}

    fake_httpx = SimpleNamespace(post=lambda *args, **kwargs: Response())
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(openrouter.time, "time", lambda: 1000.0)

    credentials = openrouter.refresh_openrouter_token("old-r")

    assert credentials.expires == 1000.0 * 1000 + 10 * 1000
    assert not hasattr(credentials, "expires_in")


def test_autoregister_refresh_accepts_sync_refresh_function():
    from providers.oauth.providers.autoregister import _make_oauth_provider
    from providers.oauth.types import OAuthCredentials

    def login_fn(**_kwargs):
        raise AssertionError("login should not be called")

    def refresh_fn(refresh):
        return OAuthCredentials(access="new-access", refresh=refresh, expires=1234.0)

    provider = _make_oauth_provider("sync", "Sync", login_fn, refresh_fn)
    refreshed = asyncio.run(provider.refresh_token(OAuthCredentials("old", "refresh-value", 1.0)))

    assert refreshed.access == "new-access"
    assert refreshed.refresh == "refresh-value"
