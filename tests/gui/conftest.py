"""
Per-subtree conftest for the gui test scripts.

The GUI integration tests drive the API through fastapi TestClient, whose
reported peer address is the literal string "testclient" (not a real
loopback address), so the loopback exemption in authentication.check_auth()
never triggers.

The production auth gate (NEXUS_ALLOW_LOCAL_ANON) is intentionally restricted
to genuine loopback peers only — see server.auth_middleware and
authentication.check_auth. To let the gui subtree exercise the API without a
real bearer token, we:
  1. opt into NEXUS_ALLOW_LOCAL_ANON for this subtree only (env-gated, OFF by
     default; the auth-denial tests under tests/test_server force it OFF), and
  2. within this test scope only, treat the synthetic "testclient" peer as
     loopback so the opt-in applies. This patch is reverted after the gui
     subtree runs (monkeypatch), so it never leaks into other subtrees such
     as tests/test_tools.

Tests that need genuine authentication (e.g. command-execution permission
flows) present a real bearer token via their own _authed_client helper.
"""
import os

os.environ.setdefault("NEXUS_ALLOW_LOCAL_ANON", "true")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _testclient_is_loopback(monkeypatch):
    """Treat the synthetic TestClient peer ("testclient") as loopback.

    Scoped to the gui test subtree. The patch is reverted automatically when
    gui tests finish, so production's genuine-loopback requirement is never
    relaxed for other test subtrees (e.g. tests/test_tools).
    """
    import security.core.auth
    import apps.api

    real_auth = authentication.is_loopback_request
    real_srv = server.is_loopback_request

    def _loopback(request) -> bool:
        client = getattr(request, "client", None)
        host = getattr(client, "host", None)
        if isinstance(host, str) and host.strip().lower() == "testclient":
            return True
        return real_auth(request) if real_auth is not None else False

    monkeypatch.setattr(authentication, "is_loopback_request", _loopback)
    monkeypatch.setattr(server, "is_loopback_request", _loopback)
