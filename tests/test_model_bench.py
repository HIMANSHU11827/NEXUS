"""Tests for the per-task model scoreboard (providers/model_bench.py)."""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from providers import model_bench
from providers.profiles import ProviderProfile, ProviderProfileStore


def _coding_task():
    return next(t for t in model_bench.load_tasks() if t["id"] == "coding")


@pytest.fixture
def empty_profiles(tmp_path, monkeypatch):
    """Hermetic profile store so ranking tests never see dev-machine state."""
    store = ProviderProfileStore(tmp_path / "profiles.json")
    monkeypatch.setattr("providers.profiles.load_profile_store", lambda: store)
    return store


def test_score_ranks_known_providers_for_coding(empty_profiles):
    task = _coding_task()
    scores = {
        "deepseek": model_bench.score_model(task, "deepseek"),
        "openrouter": model_bench.score_model(task, "openrouter"),
        "lm_studio": model_bench.score_model(task, "lm_studio"),
    }
    # Annotated benchmark scores for 'coding' put deepseek first, local last.
    assert scores["deepseek"] > scores["openrouter"] > scores["lm_studio"]
    assert 0.0 <= scores["deepseek"] <= 1.0


def test_rank_hard_filter_excludes_high_cost_on_fast_tier(empty_profiles):
    ranked = model_bench.rank_models(
        "coding",
        ["deepseek", "openrouter", "lm_studio"],
        tier="fast",
    )
    # openrouter (cost 2.5, latency 2400) fails both the cost and latency
    # hard caps of the fast tier and must be dropped before selection.
    assert ranked
    assert "openrouter" not in ranked
    assert ranked[0] == "deepseek"


def test_keyword_classifier_picks_reasoning_for_math_prompt():
    assert model_bench.classify_task("solve the quadratic equation x^2 - 4 = 0") == "reasoning"


def test_rank_returns_deterministic_fallback_on_empty_input(empty_profiles):
    assert model_bench.rank_models("coding", []) == ["deepseek"]


def test_profiles_build_keeps_cooldown_provider_out_of_top_rank(tmp_path, monkeypatch):
    """Live profile state participates in ranking (providers/profiles.py)."""
    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(
        name="cooling",
        provider="deepseek",
        type="api_key",
        api_key="x",
        cooldown_until=10**12,  # far in the future -> in cooldown
    ))
    monkeypatch.setattr("providers.profiles.load_profile_store", lambda: store)

    task = _coding_task()
    ranked = model_bench.rank_models(task, ["deepseek", "openrouter", "lm_studio"])
    # deepseek is in cooldown -> openrouter should take the top spot.
    assert ranked[0] == "openrouter"
