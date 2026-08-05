import os

from providers.factory import NexusProviderFactory


def test_offline_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv("NEXUS_OFFLINE_MODE", raising=False)
    assert NexusProviderFactory.offline_mode() is False
    monkeypatch.setenv("NEXUS_OFFLINE_MODE", "true")
    assert NexusProviderFactory.offline_mode() is True


def test_local_provider_without_api_key_is_accepted():
    provider = type("Provider", (), {"endpoint": "http://127.0.0.1:1234/v1/chat/completions"})()
    assert NexusProviderFactory._is_local_provider("lm_studio", provider)
    assert NexusProviderFactory._is_local_provider("custom", provider)


def test_offline_mode_blocks_provider_fallback(monkeypatch):
    monkeypatch.setenv("NEXUS_OFFLINE_MODE", "1")
    factory = object.__new__(NexusProviderFactory)
    assert factory.next_provider_fallback("lm_studio") is None


def test_offline_mode_rejects_explicit_remote_resolution(monkeypatch):
    monkeypatch.setenv("NEXUS_OFFLINE_MODE", "true")
    factory = object.__new__(NexusProviderFactory)
    assert factory._is_local_provider_name("lm_studio")
    assert not factory._is_local_provider_name("openrouter")
