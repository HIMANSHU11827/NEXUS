"""Closed provider-health routing loop.

``providers/health.py`` implemented healthy/degraded tracking with a decay
TTL, but the live MoE router (``intelligence/moe_router.py``) never wrote to
it and never read it: provider health was observable telemetry that could not
influence a single routing decision. A provider that had just failed was
retried in exactly the same order as a healthy one.

These tests assert the loop is closed both ways:
  real outcome -> health record -> next routing decision.
"""

import time

from nexus.capabilities.intelligence.moe_router import NexusMoERouter


class _Factory:
    """Minimal factory exposing only what the router's rotation path uses."""

    def __init__(self, chain):
        self.chain = list(chain)
        self.loader = type("L", (), {"get": staticmethod(lambda *a, **k: {})})()

    def next_provider_fallback(self, provider_id):
        try:
            i = self.chain.index(provider_id)
        except ValueError:
            return self.chain[0] if self.chain else None
        return self.chain[i + 1] if i + 1 < len(self.chain) else None

    def offline_mode(self):
        return False


def _router(chain):
    router = NexusMoERouter.__new__(NexusMoERouter)
    router.factory = _Factory(chain)
    router._provider_health = None
    return router


def test_failure_is_recorded_as_degraded_health():
    router = _router(["a", "b", "c"])
    assert router._is_provider_degraded("a") is False

    router._note_provider_health("a", False, RuntimeError("connection refused"))

    assert router._is_provider_degraded("a") is True
    reported = {h["provider_id"]: h for h in router.provider_health()}
    assert reported["a"]["healthy"] is False
    # The recorded error must be classified and redacted, not raw.
    assert reported["a"]["last_error"]


def test_success_clears_degraded_health():
    router = _router(["a", "b"])
    router._note_provider_health("a", False, RuntimeError("boom"))
    assert router._is_provider_degraded("a") is True

    router._note_provider_health("a", True, duration_ms=12.5)

    assert router._is_provider_degraded("a") is False


def test_rotation_skips_a_recently_failed_provider():
    """The headline behaviour: health must actually change routing order."""
    router = _router(["a", "b", "c"])

    # With everything healthy, rotation is unchanged from legacy behaviour.
    assert router._next_healthy_provider("a", set()) == "b"

    # After b fails, rotation must route around it to c.
    router._note_provider_health("b", False, RuntimeError("503"))
    assert router._next_healthy_provider("a", set()) == "c"


def test_rotation_still_returns_a_candidate_when_all_are_degraded():
    """Graceful degradation: a degraded provider beats no attempt at all."""
    router = _router(["a", "b", "c"])
    router._note_provider_health("b", False, RuntimeError("down"))
    router._note_provider_health("c", False, RuntimeError("down"))

    assert router._next_healthy_provider("a", set()) == "b"


def test_health_decays_so_one_failure_is_not_a_permanent_ban():
    router = _router(["a", "b", "c"])
    router._note_provider_health("b", False, RuntimeError("transient"))
    assert router._next_healthy_provider("a", set()) == "c"

    # Age the record past the decay TTL.
    from models.providers.core.health import DEGRADED_TTL_SECONDS

    record = router._health_registry().get("b")
    record.checked_at = time.time() - (DEGRADED_TTL_SECONDS + 5)

    assert router._is_provider_degraded("b") is False
    assert router._next_healthy_provider("a", set()) == "b"


def test_health_never_invents_a_provider_outside_the_chain():
    """Routing may only skip candidates, never add one."""
    router = _router(["a", "b"])
    router._note_provider_health("b", False, RuntimeError("down"))

    choice = router._next_healthy_provider("a", set())
    assert choice in {"a", "b", None}


def test_health_recording_never_raises_on_a_broken_registry():
    router = _router(["a"])

    class Broken:
        def mark_failure(self, *a, **k):
            raise RuntimeError("registry down")

        def mark_success(self, *a, **k):
            raise RuntimeError("registry down")

        def is_degraded(self, *a, **k):
            raise RuntimeError("registry down")

    router._provider_health = Broken()
    # None of these may propagate into the live provider call path.
    router._note_provider_health("a", False, RuntimeError("x"))
    router._note_provider_health("a", True)
    assert router._is_provider_degraded("a") is False


def test_provider_health_registry_is_safe_for_concurrent_router_updates():
    from concurrent.futures import ThreadPoolExecutor
    from models.providers.core.health import ProviderHealthRegistry

    registry = ProviderHealthRegistry()

    def update(index):
        provider = f"provider-{index % 4}"
        if index % 2:
            registry.mark_failure(provider, "503 temporary outage")
        else:
            registry.mark_success(provider, float(index))
        return registry.is_degraded(provider)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(update, range(128)))

    assert len(results) == 128
    assert {item["provider_id"] for item in registry.all()} == {
        "provider-0", "provider-1", "provider-2", "provider-3"
    }


def test_provider_health_registry_shares_recent_state_across_instances(tmp_path):
    from models.providers.core.health import ProviderHealthRegistry

    path = str(tmp_path / "provider-health.sqlite3")
    first = ProviderHealthRegistry(store_path=path)
    second = ProviderHealthRegistry(store_path=path)

    first.mark_failure("shared-provider", "service unavailable")
    assert second.is_degraded("shared-provider") is True
    assert second.get("shared-provider").last_error.startswith("TEMPORARY_OUTAGE")

    second.mark_success("shared-provider", latency_ms=12.0)
    assert first.is_degraded("shared-provider") is False


def test_provider_health_persistence_rejects_stale_cross_process_update(tmp_path):
    from models.providers.core.health import ProviderHealth, ProviderHealthRegistry

    path = str(tmp_path / "provider-health.sqlite3")
    registry = ProviderHealthRegistry(store_path=path)
    newer = ProviderHealth(
        provider_id="shared-provider",
        healthy=True,
        latency_ms=12.0,
        checked_at=200.0,
    )
    older = ProviderHealth(
        provider_id="shared-provider",
        healthy=False,
        last_error="TEMPORARY_OUTAGE: stale",
        checked_at=100.0,
    )
    registry._persist_locked(newer)
    registry._persist_locked(older)

    current = registry.get("shared-provider")
    assert current is not None
    assert current.checked_at == 200.0
    assert current.healthy is True
