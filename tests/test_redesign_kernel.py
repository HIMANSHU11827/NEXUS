"""Redesign tests for the kernel bootstrap: fault isolation, dependency
ordering, cold-start memoization, reload/reset, health_check and the
read-only lifecycle stage mapping.

These tests run serially against the module-global singleton, so each test
resets kernel state and restores any monkeypatched loaders via the autouse
``_clean_kernel`` fixture.
"""

import pytest

import kernel as kernel_mod
from kernel import FailedSubsystem, NexusKernel, get_nexus_kernel

# Every health row must carry this schema.
HEALTH_KEYS = {"name", "loaded", "ok", "error", "latency_ms"}


@pytest.fixture(autouse=True)
def _clean_kernel():
    """Reset the singleton + subsystem registry between tests."""
    saved = {name: dict(spec) for name, spec in kernel_mod._SUBSYSTEMS.items()}
    NexusKernel._reset_instance()
    kernel_mod._kernel = None
    yield
    NexusKernel._reset_instance()
    kernel_mod._kernel = None
    for name, spec in saved.items():
        kernel_mod._SUBSYSTEMS[name].clear()
        kernel_mod._SUBSYSTEMS[name].update(spec)


# ── 1. Subsystem fault isolation ────────────────────────────────────────────

def test_failing_subsystem_degrades_to_placeholder_and_health_reports_it():
    def _boom(self):
        raise RuntimeError("nerve sled offline")

    kernel_mod._SUBSYSTEMS["nerve"]["loader"] = _boom

    k = get_nexus_kernel()              # must not raise
    nerve = k.nerve                     # property access must not raise

    assert isinstance(nerve, FailedSubsystem)
    assert nerve.loaded is False
    assert nerve.ok is False
    assert "nerve sled offline" in nerve.msg

    report = k.health_check()           # must not raise
    assert isinstance(report, dict)
    assert "nerve" in report
    entry = report["nerve"]
    assert entry["loaded"] is False
    assert entry["ok"] is False
    assert "nerve sled offline" in str(entry["error"])
    assert entry["latency_ms"] is not None


def test_failed_subsystem_attribute_chain_soft_degrades():
    def _boom(self):
        raise RuntimeError("boom")

    kernel_mod._SUBSYSTEMS["hive"]["loader"] = _boom

    k = get_nexus_kernel()
    hive = k.hive
    # Attribute chains on a failed subsystem never raise.
    assert bool(hive) is False
    assert repr(hive.list_personas()) == "<missing>"
    # Failed placeholder caches so it is not retried on every access.
    assert k.hive is hive


# ── 2. Dependency ordering ──────────────────────────────────────────────────

def test_dependency_failure_skips_dependent_subsystem():
    def _boom(self):
        raise ImportError("moe broke")

    kernel_mod._SUBSYSTEMS["moe"]["loader"] = _boom  # moa lists after=("moe",)

    k = get_nexus_kernel()
    moa = k.moa                        # depends on moe -> skipped, not crashed

    assert isinstance(moa, FailedSubsystem)
    assert moa.skipped is True
    assert "moe" in moa.reason
    assert "dependency 'moe' failed" in moa.msg

    report = k.health_check()
    assert report["moe"]["loaded"] is False
    assert report["moa"]["loaded"] is False
    assert "dependency 'moe' failed" in str(report["moa"]["error"])


def test_subsystem_loads_dependencies_before_dependent():
    k = get_nexus_kernel()
    # Accessing moa must load moe first (undeclared in _instances yet).
    moa = k.moa
    assert moa is not None and not isinstance(moa, FailedSubsystem)
    assert isinstance(k._instances.get("moe"), object)
    assert isinstance(k._instances.get("moa"), object)


# ── 3. Cold-start performance: memoization + latency ────────────────────────

def test_subsystem_loads_once_and_latency_is_recorded():
    loads = {"spy": 0}

    def _spy(self):
        loads["spy"] += 1
        return {"spy": True}

    kernel_mod._SUBSYSTEMS["indexer"]["loader"] = _spy

    k = get_nexus_kernel()
    assert k.indexer["spy"] is True
    assert k.indexer is k.indexer        # memoized — same object
    assert loads["spy"] == 1             # no double loading

    assert "indexer" in k._load_latency_ms
    assert k._load_latency_ms["indexer"] >= 0


def test_get_nexus_kernel_is_lazy_and_subsystems_not_preloaded():
    k = get_nexus_kernel()
    assert k._instances == {}            # nothing pre-loaded at bootstrap
    _ = k.config
    assert set(k._instances) == {"config"}


# ── 4. Reset / reload ───────────────────────────────────────────────────────

def test_reload_reruns_loaders_and_records_reason():
    calls = {"n": 0}

    def _counting(self):
        calls["n"] += 1
        return {"ok": True}

    kernel_mod._SUBSYSTEMS["config"]["loader"] = _counting

    k = get_nexus_kernel()
    _ = k.config
    assert calls["n"] == 1
    _ = k.config                          # memoized — not re-run
    assert calls["n"] == 1

    result = k.reload(reason="upgrade-v2")
    assert result["reason"] == "upgrade-v2"
    assert k._reload_reason == "upgrade-v2"
    assert k._reload_history[-1]["reason"] == "upgrade-v2"
    assert k._reload_history[-1]["dropped"] == 1

    _ = k.config                          # cache dropped -> loader re-runs
    assert calls["n"] == 2


def test_reset_drops_cached_singleton():
    k1 = get_nexus_kernel()
    k1._instances["config"] = object()
    assert k1.reset() is True
    k2 = get_nexus_kernel()
    assert k2 is not k1
    assert k2._instances == {}


def test_reload_recovers_failed_subsystem():
    def _boom(self):
        raise RuntimeError("first time")

    kernel_mod._SUBSYSTEMS["plugins"]["loader"] = _boom

    k = get_nexus_kernel()
    assert isinstance(k.plugins, FailedSubsystem)
    assert k.health_check()["plugins"]["loaded"] is False

    # "Fix" the loader and rebuild; reload should drop the placeholder.
    kernel_mod._SUBSYSTEMS["plugins"]["loader"] = (
        lambda self: {"plugins_ok": True}
    )
    k.reload(reason="fix-applied")
    assert k.plugins == {"plugins_ok": True}


# ── 5. health_check invariants ──────────────────────────────────────────────

def test_health_check_never_raises_and_covers_every_subsystem():
    k = get_nexus_kernel()
    report = k.health_check()
    assert isinstance(report, dict)
    assert set(report) == set(kernel_mod._SUBSYSTEMS)
    for row in report.values():
        assert HEALTH_KEYS <= set(row)

    # Even a loader that always raises cannot make health_check raise.
    def _always_boom(self):
        raise RuntimeError("still down")

    kernel_mod._SUBSYSTEMS["hal"]["loader"] = _always_boom
    k.reset()
    k2 = get_nexus_kernel()
    report2 = k2.health_check()
    assert report2["hal"]["loaded"] is False
    assert report2["hal"]["ok"] is False
    assert "still down" in str(report2["hal"]["error"])


# ── 6. Optional lifecycle integration (read-only) ───────────────────────────

def test_get_component_stages_maps_substates_to_lifecycle_names():
    k = get_nexus_kernel()
    stages = k.get_component_stages()
    assert isinstance(stages, dict)
    assert set(stages) == set(kernel_mod._SUBSYSTEMS)
    allowed = {"created", "ready", "running", "failed", "quarantined"}
    assert all(value in allowed for value in stages.values())

    # Loaded subsystems map to running/ready.
    _ = k.moe
    loaded = k.get_component_stages()
    assert loaded["moe"] in {"running", "ready"}

    # Failed subsystems map to failed.
    def _boom(self):
        raise RuntimeError("boom")

    kernel_mod._SUBSYSTEMS["prover"]["loader"] = _boom
    k.reset()
    k2 = get_nexus_kernel()
    _ = k2.prover
    assert k2.get_component_stages()["prover"] == "failed"


# ── 7. Public API preserved ─────────────────────────────────────────────────

def test_public_api_and_backward_compat_surface():
    k = get_nexus_kernel()
    for attr in ("config", "moe", "moa", "nerve", "omni", "hyper", "researcher",
                 "persistence", "hal", "horizons", "local_brain", "trainer",
                 "indexer", "intent", "prover", "tools", "telemetry", "rag",
                 "hive", "plugins"):
        assert hasattr(k, attr), f"missing subsystem property: {attr}"
    for attr in ("boot", "get_stats", "reinforce", "health_check", "reload",
                 "reset", "get_component_stages", "_get_or_init", "_component"):
        assert callable(getattr(k, attr)), f"missing method: {attr}"

    # _get_or_init backward-compat path (loader receives no self).
    class Fake:
        def ping(self):
            return "pong"

    out = k._get_or_init("_fake", lambda: Fake())
    assert out.ping() == "pong"
    assert k._instances["_fake"] is out
