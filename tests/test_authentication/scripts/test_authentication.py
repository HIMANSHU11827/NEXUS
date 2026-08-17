__version__ = "1.0.0"

import os
from unittest.mock import MagicMock, patch

import pytest

from security.core.auth import (
    OAUTH_PROVIDERS,
    AuthUser,
    _generate_state,
    _verify_state,
    check_auth,
    get_allowed_users,
    get_oauth_authorize_url,
    handle_oauth_callback,
    is_gateway_authorized,
    is_public_path,
    validate_dashboard_token,
)


class TestTokenValidation:
    def test_no_token_set_rejects_bearer_tokens(self):
        with patch("security.core.auth._AUTH_TOKEN", ""):
            assert validate_dashboard_token("anything") is False
            assert validate_dashboard_token("") is False

    def test_valid_token(self):
        with patch("security.core.auth._AUTH_TOKEN", "my-secret-token"):
            assert validate_dashboard_token("my-secret-token") is True

    def test_invalid_token(self):
        with patch("security.core.auth._AUTH_TOKEN", "real-token"):
            assert validate_dashboard_token("wrong-token") is False

    def test_empty_token_with_env_set(self):
        with patch("security.core.auth._AUTH_TOKEN", "real-token"):
            assert validate_dashboard_token("") is False

    def test_constant_time_compare(self):
        with patch("security.core.auth._AUTH_TOKEN", "a" * 1000):
            assert validate_dashboard_token("a" * 1000) is True
            assert validate_dashboard_token("b" * 1000) is False


class TestGatewayAuth:
    def test_allowed_users_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            users = get_allowed_users()
            assert users.get("telegram") == []

    def test_allowed_users_with_star(self):
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS": "*"}, clear=True):
            users = get_allowed_users()
            assert "*" in users.get("telegram", [])

    def test_is_gateway_authorized_star(self):
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS": "*"}, clear=True):
            assert is_gateway_authorized("telegram", "any_user") is True

    def test_is_gateway_authorized_specific(self):
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS": "user1,user2"}, clear=True):
            assert is_gateway_authorized("telegram", "user1") is True
            assert is_gateway_authorized("telegram", "user3") is False

    def test_is_gateway_authorized_unknown_platform(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_gateway_authorized("unknown", "user") is False


class TestOAuthState:
    def test_generate_and_verify(self):
        state = _generate_state("google")
        assert _verify_state(state, "google") is True

    def test_wrong_provider_fails(self):
        state = _generate_state("google")
        assert _verify_state(state, "github") is False

    def test_tampered_state_fails(self):
        state = _generate_state("google")
        tampered = "bad" + state[3:]
        assert _verify_state(tampered, "google") is False

    def test_expired_state_fails(self):
        with patch("time.time", return_value=0):
            state = _generate_state("google")
        with patch("time.time", return_value=1001):
            assert _verify_state(state, "google", max_age=600) is False


_TEST_OAUTH = {
    "google": {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "client_id": "test-github-id",
        "client_secret": "test-github-secret",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


class TestOAuthFlow:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            get_oauth_authorize_url("nonexistent", "http://localhost/callback")

    def test_authorize_url_contains_params(self):
        with patch("security.core.auth.OAUTH_PROVIDERS", _TEST_OAUTH):
            url, state = get_oauth_authorize_url("google", "http://localhost:5173/callback")
            assert url.startswith("https://accounts.google.com/")
            assert "client_id=" in url
            assert len(state) > 10

    def test_authorize_url_encodes_redirect_uri_and_scope(self):
        with patch("security.core.auth.OAUTH_PROVIDERS", _TEST_OAUTH):
            url, _state = get_oauth_authorize_url("google", "http://localhost:5173/callback?next=/a b")
            assert "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fcallback%3Fnext%3D%2Fa+b" in url
            assert "scope=openid+email+profile" in url

    @pytest.mark.asyncio
    async def test_handle_callback_unknown_provider(self):
        result = await handle_oauth_callback("unknown", "code", "state", "uri")
        assert not result.success
        assert "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_handle_callback_bad_state(self):
        with patch("security.core.auth.OAUTH_PROVIDERS", _TEST_OAUTH):
            result = await handle_oauth_callback("google", "code", "bad-state", "uri")
            assert not result.success
            assert "Invalid or expired state" in result.error

    @pytest.mark.asyncio
    async def test_handle_callback_returns_generic_error_on_unexpected_exception(self, monkeypatch):
        state = _generate_state("google")

        class BoomClient:
            async def __aenter__(self):
                raise RuntimeError("client_secret=do-not-return")

            async def __aexit__(self, *args):
                return None

        fake_httpx = MagicMock()
        fake_httpx.AsyncClient.return_value = BoomClient()
        fake_httpx.TimeoutException = TimeoutError
        monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

        with patch("security.core.auth.OAUTH_PROVIDERS", _TEST_OAUTH):
            result = await handle_oauth_callback("google", "code", state, "uri")

        assert result.success is False
        assert result.error == "OAuth callback failed"

    def test_provider_configs(self):
        assert isinstance(OAUTH_PROVIDERS, dict)


class TestAuthUser:
    def test_to_dict(self):
        user = AuthUser(provider="google", sub="123", name="Test User", email="test@example.com")
        d = user.to_dict()
        assert d["provider"] == "google"
        assert d["name"] == "Test User"
        assert d["sub"] == "123"

    def test_id_property(self):
        user = AuthUser(provider="github", sub="456")
        assert user.id == "github:456"


class TestPublicPaths:
    def test_known_public_paths(self):
        for path in ("/api/health", "/api/auth/login"):
            assert is_public_path(path)

    def test_private_paths(self):
        for path in ("/api/chat", "/api/manage", "/api/run"):
            assert not is_public_path(path)


class TestCheckAuth:
    def test_no_auth_returns_none(self):
        request = MagicMock()
        request.session = {}
        request.headers = {"authorization": ""}
        assert check_auth(request) is None

    def test_session_auth(self):
        user = AuthUser(provider="google", sub="123", name="Test")
        request = MagicMock()
        request.session = {"user": user.to_dict()}
        request.headers = {}
        result = check_auth(request)
        assert result is not None
        assert result.name == "Test"

    def test_bearer_token(self):
        with patch("security.core.auth._AUTH_TOKEN", "my-token"):
            request = MagicMock()
            request.session = {}
            request.headers = {"Authorization": "Bearer my-token"}
            result = check_auth(request)
            assert result is not None
            assert result.provider == "token"

    def test_bearer_wrong_token(self):
        with patch("security.core.auth._AUTH_TOKEN", "real-token"):
            request = MagicMock()
            request.session = {}
            request.headers = {"authorization": "Bearer wrong"}
            assert check_auth(request) is None
