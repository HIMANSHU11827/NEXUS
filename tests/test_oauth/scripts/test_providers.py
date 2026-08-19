import asyncio
import json
import sys
from types import SimpleNamespace

from models.providers.auth.oauth.providers.autoregister import register_all_oauth_providers
from models.providers.auth.oauth.registry import get_oauth_providers, reset_oauth_providers
from models.providers.auth.oauth.types import OAuthCredentials


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
            if p.id == "gemini":
                # Gemini OAuth keys are the JSON {"token": ..., "projectId": ...}
                # shape the client parses into an Authorization: Bearer header.
                parsed = json.loads(key)
                assert parsed["token"] == "test_key"
            else:
                assert key == "test_key"

    def test_each_provider_has_id_and_name(self):
        for p in get_oauth_providers():
            assert p.id
            assert p.name


def test_openrouter_refresh_raises_with_guidance():
    from models.providers.auth.oauth.providers import openrouter

    credentials = OAuthCredentials(
        access="key", refresh="", expires=openrouter.time.time() * 1000 + 3600000
    )
    try:
        openrouter.refresh_openrouter_token(credentials)
        raise AssertionError("refresh_openrouter_token should raise")
    except RuntimeError as exc:
        assert "do not rotate" in str(exc)


def test_openrouter_login_uses_absolute_expiry_ms(monkeypatch):
    from models.providers.auth.oauth.providers import openrouter
    from models.providers.auth.oauth.types import OAuthAuthorizationInput

    captured = {}
    async def fake_wait_callback(**kwargs):
        return OAuthAuthorizationInput(code="fake-code", state="test-state")

    class AsyncResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"key": "sk-or-v1-test", "user_id": "user-1"}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return AsyncResponse()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(openrouter, "generate_oauth_state", lambda: "test-state")
    monkeypatch.setattr(openrouter, "wait_for_local_oauth_callback", fake_wait_callback)
    monkeypatch.setattr(openrouter.time, "time", lambda: 2000.0)

    async def run():
        return await openrouter.login_openrouter(
            on_auth=lambda info: None,
            on_prompt=lambda _: "",
            on_progress=lambda _: None,
        )

    credentials = asyncio.run(run())

    assert captured["url"] == "https://openrouter.ai/api/v1/auth/keys"
    assert set(captured["json"]) == {"code", "code_verifier", "code_challenge_method"}
    assert credentials.access == "sk-or-v1-test"
    assert credentials.account_id == "user-1"
    assert credentials.expires == 2000.0 * 1000 + openrouter.KEY_LIFETIME_MS


def test_provider_constants_match_upstream_clients():
    from models.providers.auth.oauth.providers import claude, codex, grok, minimax

    assert claude.CLIENT_ID == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    assert claude.AUTHORIZE_URL == "https://claude.ai/oauth/authorize"
    assert claude.TOKEN_URL == "https://platform.claude.com/v1/oauth/token"
    assert "org:create_api_key" in claude.SCOPES
    assert "user:profile" in claude.SCOPES

    assert codex.CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert codex.AUTHORIZE_URL == "https://auth.openai.com/oauth/authorize"
    assert codex.TOKEN_URL == "https://auth.openai.com/oauth/token"
    assert codex.SCOPES == "openid profile email offline_access"

    assert grok.CLIENT_ID == "b1a00492-073a-47ea-816f-4c329264a828"
    assert "grok-cli:access" in grok.SCOPES
    assert grok.ISSUER == "https://auth.x.ai"

    assert minimax.MINIMAX_OAUTH_CONFIG["cn"]["oauth_base_url"] == "https://account.minimaxi.com"
    assert minimax.MINIMAX_OAUTH_CONFIG["global"]["oauth_base_url"] == "https://account.minimax.io"
    assert minimax.MINIMAX_OAUTH_CONFIG["cn"]["client_id"] == "78257093-7e40-4613-99e0-527b14b39113"
    assert "model.completion" in minimax.SCOPES


def test_autoregister_refresh_accepts_sync_refresh_function():
    from models.providers.auth.oauth.providers.autoregister import _make_oauth_provider
    from models.providers.auth.oauth.types import OAuthCredentials

    def login_fn(**_kwargs):
        raise AssertionError("login should not be called")

    def refresh_fn(credentials):
        return OAuthCredentials(access="new-access", refresh=credentials.refresh, expires=1234.0)

    provider = _make_oauth_provider("sync", "Sync", login_fn, refresh_fn)
    refreshed = asyncio.run(provider.refresh_token(OAuthCredentials("old", "refresh-value", 1.0)))

    assert refreshed.access == "new-access"
    assert refreshed.refresh == "refresh-value"