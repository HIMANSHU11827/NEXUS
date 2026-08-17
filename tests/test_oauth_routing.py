"""OAuth token routing must land on real runtime endpoints, not UniversalProvider's
localhost placeholder.

Regression guard: providers/factory.py maps several OAuth-login providers (codex,
claude, github_copilot, minimax, chutes) to UniversalProvider, whose default
endpoint is ``http://localhost:8000/v1/chat/completions``. An OAuth token stored
by ``nexus auth login <provider>`` is routed through that mapping, so any provider
that gains a ``providers:`` config entry must expose a REAL endpoint there, and
blocked providers must be documented under ``documented_blocker`` rather than
given a fabricated endpoint.
"""

from pathlib import Path

import yaml

from models.providers.core import factory as factory_module
from models.providers.core.factory import NexusProviderFactory


def _provider_yml() -> dict:
    path = Path(__file__).resolve().parents[1] / "configure" / "provider.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _configured_endpoints() -> dict:
    cfg = _provider_yml()
    providers = cfg.get("providers", {}) if isinstance(cfg, dict) else {}
    return {
        pid: (entry.get("endpoint") or "").strip()
        for pid, entry in providers.items()
        if isinstance(entry, dict) and (entry.get("endpoint") or "").strip()
    }


def test_grok_oauth_provider_resolves_real_endpoint_from_config(monkeypatch):
    cfg = _provider_yml()
    expected = cfg["providers"]["grok"]["endpoint"]

    # Avoid all network: stub OAuth token resolution AND env key lookups.
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda *_a, **_k: "test-bearer-token")
    monkeypatch.setattr(factory_module, "_environment_value", lambda *_a, **_k: "")

    factory = NexusProviderFactory()
    provider = factory.get_provider_by_name("cloud", "grok")

    assert provider is not None
    assert provider.endpoint == expected
    assert provider.endpoint != "http://localhost:8000/v1/chat/completions"
    assert provider.api_key == "test-bearer-token"
    assert provider.headers.get("Authorization") == "Bearer test-bearer-token"


def test_oauth_resolution_runs_without_named_profile(monkeypatch):
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda provider, profile=None: "oauth-token" if provider == "grok" else None)
    monkeypatch.setattr(factory_module, "_environment_value", lambda *_a, **_k: "")
    provider = NexusProviderFactory().get_provider_by_name("cloud", "grok")
    assert provider.api_key == "oauth-token"
    assert provider._credential_id == "oauth:grok"


def test_oauth_tokens_route_away_from_localhost_placeholder():
    for pid, ep in _configured_endpoints().items():
        if any(host in ep.lower() for host in ("127.0.0.1", "localhost")):
            continue  # intentional local server (e.g. language-models/lm_studio)
        assert "localhost:8000" not in ep, f"{pid} still routes to the placeholder: {ep}"
        assert ep.startswith("https://"), f"{pid} must use https: {ep}"


def test_blocked_oauth_providers_are_documented_not_fabricated():
    cfg = _provider_yml()
    blocked = set(cfg.get("documented_blocker", {}).keys())

    # Auth-registered ids (`nexus auth login <id>`) that route to UniversalProvider.
    auth_routed = {"codex", "claude", "github-copilot", "minimax", "chutes"}
    # The factory mapping additionally uses the underscore spelling.
    factory_routed = {"github_copilot"}

    for pid in auth_routed:
        assert pid in blocked, f"{pid} must be listed in documented_blocker"

    endpoints = _configured_endpoints()
    for pid in auth_routed | factory_routed:
        assert pid not in endpoints, f"{pid} must not be given a fabricated endpoint"
