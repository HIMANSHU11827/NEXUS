"""Health must influence the PRIMARY provider pick, not only rotation.

``intelligence/moe_router.py`` closed the rotation half of the provider-health
loop (``_next_healthy_provider``), but the *first* provider of every turn is
chosen by ``_ranked_primary`` -> ``model_bench.rank_models``, which was called
WITHOUT the ``health=`` argument. ``providers/router.py`` (ModelRouter) already
passes it (router.py:520), so the degrade penalty existed but was disconnected
on the live MoE path used by the V5 loop (kernel/__init__.py:206).

Result before the fix: under load, a provider that had just failed was still
selected first on every subsequent turn, burning one provider request per turn
before rotation could skip it.
"""

from nexus.capabilities.intelligence.moe_router import NexusMoERouter


class _Loader:
    def __init__(self, chain):
        self._chain = list(chain)

    def get(self, key, default=None):
        if key == "provider":
            return {"fallback_chain": list(self._chain), "default_provider": self._chain[0]}
        return default if default is not None else {}


class _Factory:
    def __init__(self, chain):
        self.chain = list(chain)
        self.loader = _Loader(chain)

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
    router.provider_override = ""
    router.profile_override = ""
    router._provider_health = None
    return router


# A prompt that the keyword classifier resolves to the "coding" task, so the
# benchmark ranking path (not the plain default_provider path) is exercised.
_CODING = [{"role": "user", "content": "debug this python function in my script"}]


def test_ranked_primary_prefers_healthy_provider_over_degraded_one():
    router = _router(["prov_alpha", "prov_beta"])

    # Baseline: with no health signal the configured chain order wins.
    assert router._ranked_primary(_CODING) == "prov_alpha"

    # A real recorded failure must move the primary pick to the healthy peer.
    router._note_provider_health("prov_alpha", False, RuntimeError("connection refused"))
    assert router._is_provider_degraded("prov_alpha") is True

    assert router._ranked_primary(_CODING) == "prov_beta"


def test_get_provider_name_uses_health_aware_ranking():
    router = _router(["prov_alpha", "prov_beta"])
    router._note_provider_health("prov_alpha", False, RuntimeError("503 upstream"))

    assert router._get_provider_name(_CODING) == "prov_beta"


def test_explicit_override_still_wins_over_health():
    """Health may only reorder candidates; it must never override the caller."""
    router = _router(["prov_alpha", "prov_beta"])
    router._note_provider_health("prov_alpha", False, RuntimeError("down"))
    router.provider_override = "prov_alpha"

    assert router._get_provider_name(_CODING) == "prov_alpha"


def test_all_degraded_still_returns_a_candidate():
    router = _router(["prov_alpha", "prov_beta"])
    router._note_provider_health("prov_alpha", False, RuntimeError("down"))
    router._note_provider_health("prov_beta", False, RuntimeError("down"))

    assert router._ranked_primary(_CODING) in {"prov_alpha", "prov_beta"}
