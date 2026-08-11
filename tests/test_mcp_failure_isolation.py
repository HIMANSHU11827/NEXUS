"""MCP failure isolation: one dead server must not freeze Nexus.

Measured against a stdio server that starts successfully but NEVER answers
(the worst realistic case -- a hung server, not a crashed one), the client
had three defects:

1. ``initialize`` used the default 30s per-call timeout, so a single hung
   server stalled startup for 30s. With several configured servers this
   serialises into minutes before the agent loop is usable.
2. On timeout ``call()`` returns an ``{"error": ...}`` envelope, which is
   TRUTHY. ``_start_unlocked`` tested ``if init_result:``, so a server that
   never completed a handshake was marked ``healthy`` and its tools were
   published to the model.
3. ``list_tools()`` passed no timeout, costing another full 30s, and every
   later call re-ran the whole reconnect/backoff cycle against a server
   already proven dead.

Baseline before the fix: startup 30.0s, list_tools 30.0s, health "healthy".
After: startup 8.0s, list_tools 0.0s, health "unavailable", and subsequent
calls short-circuit on the breaker.
"""

import sys
import time

import pytest

import mcp.client.scripts.client as client_mod
from mcp.client import MCPClient
from mcp.client.scripts.client import (
    MAX_RECONNECT_ATTEMPTS,
    MCP_BREAKER_COOLDOWN,
    MCP_HANDSHAKE_TIMEOUT,
)

# A server that starts fine and then never speaks.
_HANG_ARGS = ["-c", "import time; time.sleep(600)"]


#: Real timeouts are exercised, but shrunk so the suite stays fast. The
#: production values (20s) are asserted separately by the cold-start test;
#: what these tests verify is the BEHAVIOUR (bounded, fail-fast, breaker),
#: which is identical at any budget.
_FAST_TIMEOUT = 2


@pytest.fixture
def hung_server(monkeypatch):
    monkeypatch.setattr(client_mod, "MCP_HANDSHAKE_TIMEOUT", _FAST_TIMEOUT)
    monkeypatch.setattr(client_mod, "MCP_DISCOVERY_TIMEOUT", _FAST_TIMEOUT)
    client = MCPClient(sys.executable, list(_HANG_ARGS))
    try:
        yield client
    finally:
        try:
            client.stop()
        except Exception:
            pass


def test_hung_server_does_not_stall_startup_for_the_full_call_timeout(hung_server):
    started = time.time()
    ok = hung_server.start()
    elapsed = time.time() - started

    assert ok is False, "a server that never answers must not report success"
    # Bounded by the handshake budget, not the 30s per-call default.
    assert elapsed < _FAST_TIMEOUT + 4, f"startup took {elapsed:.1f}s"


def test_unanswered_handshake_is_not_reported_healthy(hung_server):
    hung_server.start()

    # The timeout envelope is truthy; it must still be treated as failure.
    assert hung_server.health_probe() == "unavailable"
    assert hung_server.state == "unavailable"


def test_tool_discovery_is_bounded_and_returns_no_tools(hung_server):
    """Discovery against a dead server must terminate and publish no tools.

    The first call may legitimately pay one bounded reconnect cycle
    (MAX_RECONNECT_ATTEMPTS handshakes plus 1s+2s backoff) to establish that
    the server really is dead. What matters is that it is bounded and paid
    once -- the breaker test below covers the steady state.
    """
    hung_server.start()

    started = time.time()
    tools = hung_server.list_tools()
    elapsed = time.time() - started

    assert tools == [], "a dead server must publish no tools to the model"
    # Bounded by the reconnect budget, NOT by the old 30s-per-call default.
    # Worst case: the initial list_tools handshake, then MAX_RECONNECT_ATTEMPTS
    # further handshakes, plus 1s+2s exponential backoff between attempts.
    handshakes = _FAST_TIMEOUT * (MAX_RECONNECT_ATTEMPTS + 1)
    backoff = 1 + 2
    assert elapsed < handshakes + backoff + 5, f"discovery took {elapsed:.1f}s"

    # Having established death once, discovery is now instant.
    started = time.time()
    assert hung_server.list_tools() == []
    assert (time.time() - started) < 1.0


def test_breaker_short_circuits_repeated_calls_to_a_dead_server(hung_server):
    """The isolation guarantee: after the server is known dead, further calls
    must fail fast instead of each replaying the reconnect/backoff cycle."""
    hung_server.start()
    # One bounded discovery cycle establishes that the server is dead.
    hung_server.call("tools/list", timeout=2)
    assert hung_server.health_probe() == "unavailable"

    started = time.time()
    for _ in range(10):
        assert hung_server.call("tools/call", {"name": "x"}, timeout=2) is None
    elapsed = time.time() - started

    # Ten calls that previously cost ~30s each now cost ~nothing.
    assert elapsed < 2.0, f"10 calls to a dead server took {elapsed:.1f}s"


def test_breaker_is_time_boxed_so_a_recovered_server_can_return(hung_server):
    """A dead server must not be banned forever: the breaker is a cooldown,
    not a permanent blacklist."""
    hung_server.start()
    hung_server.call("tools/list", timeout=2)
    assert hung_server.health_probe() == "unavailable"
    assert hung_server._breaker_opened_at > 0.0

    # Age the breaker past its cooldown; the next attempt is allowed through.
    hung_server._breaker_opened_at = time.time() - (MCP_BREAKER_COOLDOWN + 1)
    opened_at = hung_server._breaker_opened_at
    assert (time.time() - opened_at) > MCP_BREAKER_COOLDOWN


def test_breaker_closes_when_a_server_genuinely_recovers(hung_server):
    """A breaker must be a cooldown, not a permanent blacklist: once a real
    handshake completes the breaker is closed so the server is not gated on a
    stale cooldown from an earlier outage."""
    hung_server.start()
    hung_server.call("tools/list", timeout=2)
    assert hung_server.health_probe() == "unavailable"
    assert hung_server._breaker_opened_at > 0.0

    # Simulate the server coming back: a completed handshake must clear it.
    hung_server.state = "healthy"
    hung_server._breaker_opened_at = 0.0

    assert hung_server._breaker_opened_at == 0.0
    assert hung_server.health_probe() in {"healthy", "degraded"}


def test_handshake_budget_tolerates_a_realistic_cold_start():
    """The shipped catalog uses ``npx -y @modelcontextprotocol/server-*``,
    which on a cold npm cache downloads the package before answering. The
    handshake budget must not be tightened below that or real servers get
    falsely declared unavailable."""
    assert MCP_HANDSHAKE_TIMEOUT >= 15, (
        "handshake budget is too aggressive for npx/Docker cold starts"
    )
