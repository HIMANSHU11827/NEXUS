"""
Per-subtree conftest for the gui test scripts.

The GUI integration tests drive the API through fastapi TestClient, whose
reported peer address is the literal string "testclient" (not 127.0.0.1), so
the loopback exemption in authentication.check_auth() never triggers. Rather
than weakening the real auth control, we flip the explicit
NEXUS_ALLOW_LOCAL_ANON opt-in for this subtree only. It is env-gated and OFF
by default, and deliberately scoped to tests/gui so the auth-denial tests
under tests/test_server still exercise the real 401 path.

Tests that need genuine authentication (e.g. command-execution permission
flows) present a real bearer token via their own _authed_client helper, which
works fine alongside this opt-in.
"""
import os

os.environ.setdefault("NEXUS_ALLOW_LOCAL_ANON", "true")
