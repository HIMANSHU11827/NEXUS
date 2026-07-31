"""Targeted verification of server.auth_middleware loopback hardening.

Proves that the ``NEXUS_ALLOW_LOCAL_ANON`` opt-in CANNOT bypass authentication
for non-loopback peers (LAN, tunnels, container bridges, the pytest TestClient
whose peer is literally ``testclient``). The loopback decision is delegated to
``authentication.is_loopback_request``, which only trusts genuine loopback
addresses and treats anything it cannot positively identify as remote.

The ``authentication`` module (``is_loopback_request``, ``check_auth``,
``AuthUser``, ``validate_dashboard_token``) is intentionally kept REAL here so
the hardening is actually exercised — only heavier/irrelevant server deps are
mocked for the import.
"""
import os
import sys
from unittest.mock import patch

import pytest
from starlette.datastructures import State
from starlette.requests import Request
from starlette.responses import JSONResponse


# ── Import guard: keep authentication REAL, mock only heavy/irrelevant deps ──
@pytest.fixture(autouse=True)
def _import_mocks():
    patches = [
        patch("dotenv.load_dotenv"),
        patch("orchestrators.loop.NexusLoop"),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.safe_dump"),
    ]
    for p in patches:
        p.start()
    for mod in list(sys.modules.keys()):
        if mod == "server" or mod.startswith("server."):
            del sys.modules[mod]
    yield
    for p in patches:
        p.stop()


def _make_request(path, client_host="testclient", port=50000, headers=None):
    """Build a Starlette Request with an explicit (mockable) peer address."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": (client_host, port) if client_host is not None else None,
    }
    req = Request(scope)
    req._state = State()  # ensure request.state assignment works
    return req


async def _call_middleware(mw, req):
    async def call_next(request):
        return JSONResponse({"ok": True})

    return await mw(req, call_next)


# ── 1. is_loopback_request host classification ──────────────────────────────
class TestIsLoopbackRequest:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("127.0.0.1", True),
            ("::1", True),
            ("localhost", True),
            ("::ffff:127.0.0.1", True),
            (" 127.0.0.1 ", True),   # strip()/lower() must still match
            ("192.168.1.5", False),  # RFC1918 LAN
            ("10.0.0.1", False),     # RFC1918 LAN
            ("172.16.5.4", False),   # RFC1918 LAN
            ("169.254.1.1", False),  # link-local
            ("0.0.0.0", False),      # wildcard / not loopback
            ("::ffff:192.168.1.1", False),  # IPv4-mapped NON-loopback
            ("example.com", False),  # hostname spoof attempt via header
            ("testclient", False),   # pytest TestClient peer MUST NOT be trusted
        ],
    )
    def test_host_classification(self, host, expected):
        from authentication import is_loopback_request

        req = _make_request("/api/sessions", client_host=host)
        assert is_loopback_request(req) is expected

    def test_missing_client_is_remote(self):
        from authentication import is_loopback_request

        req = _make_request("/api/sessions", client_host=None)
        assert is_loopback_request(req) is False


# ── 2. check_auth() honors loopback restriction on the anon flag ─────────────
class TestCheckAuthHardening:
    def _req(self, client_host):
        return _make_request("/api/sessions", client_host=client_host)

    def test_anon_flag_off_requires_auth_even_on_loopback(self):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "false"}):
            from authentication import check_auth

            assert check_auth(self._req("127.0.0.1")) is None

    def test_anon_flag_on_loopback_bypasses(self):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            from authentication import check_auth

            user = check_auth(self._req("127.0.0.1"))
            assert user is not None
            assert user.provider == "local"
            assert user.sub == "dashboard"

    def test_anon_flag_on_lan_peer_still_requires_auth(self):
        # THE CORE HARDENING: a remote peer must never be trusted by the flag.
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            from authentication import check_auth

            assert check_auth(self._req("192.168.1.50")) is None

    def test_anon_flag_on_testclient_peer_requires_auth(self):
        # The pytest TestClient peer is "testclient", not a real loopback addr.
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            from authentication import check_auth

            assert check_auth(self._req("testclient")) is None

    def test_valid_bearer_token_authenticates_remote_peer(self):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "false"}), patch(
            "authentication._AUTH_TOKEN", "secret-token"
        ):
            from authentication import check_auth

            req = _make_request(
                "/api/sessions",
                client_host="192.168.1.9",
                headers=[(b"authorization", b"Bearer secret-token")],
            )
            user = check_auth(req)
            assert user is not None
            assert user.provider == "token"


# ── 3. server.auth_middleware end-to-end loopback enforcement ───────────────
class TestAuthMiddlewareHardening:
    @pytest.fixture
    def mw(self):
        from server import auth_middleware

        return auth_middleware

    async def test_default_denies_protected_endpoint_without_token(self, mw):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "false"}):
            resp = await _call_middleware(
                mw, _make_request("/api/sessions", client_host="192.168.1.9")
            )
            assert resp.status_code == 401

    async def test_anon_flag_on_loopback_passes_through(self, mw):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            resp = await _call_middleware(
                mw, _make_request("/api/sessions", client_host="127.0.0.1")
            )
            assert resp.status_code == 200

    async def test_anon_flag_on_lan_peer_is_denied(self, mw):
        # Hardening at the middleware boundary: LAN peer + flag=true still 401.
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            resp = await _call_middleware(
                mw, _make_request("/api/sessions", client_host="192.168.1.9")
            )
            assert resp.status_code == 401

    async def test_anon_flag_on_ipv6_loopback_passes_through(self, mw):
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
            resp = await _call_middleware(
                mw, _make_request("/api/sessions", client_host="::1")
            )
            assert resp.status_code == 200

    async def test_public_path_skips_auth_regardless_of_peer(self, mw):
        # /api/health is in _AUTH_SKIP_PATHS; must never require auth.
        with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "false"}):
            resp = await _call_middleware(
                mw, _make_request("/api/health", client_host="203.0.113.7")
            )
            assert resp.status_code == 200
