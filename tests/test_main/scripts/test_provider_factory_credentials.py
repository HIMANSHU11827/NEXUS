from models.providers.core import factory as factory_module
from models.providers.core.factory import NexusProviderFactory
from models.providers.auth.oauth.types import OAuthCredentials


class _Loader:
    def __init__(self, config):
        self.config = config

    @staticmethod
    def get(*_args):
        return {}

    def get_system(self, _key, default=None):
        return default

    def get_provider_config(self, _provider_id):
        return self.config


class _EnvLoader:
    @staticmethod
    def get_provider_config(_provider_id):
        return {"api_key": "${DEEPSEEK_API_KEY}", "model": "test-model"}


class _Provider:
    def __init__(self):
        self.api_key = "base-key"
        self.model = ""
        self.endpoint = ""
        self.headers = {"Authorization": "Bearer base-key"}


class _Store:
    def __init__(self, credentials):
        self.credentials = credentials
        self.saved = None

    def get(self, _provider_id):
        return self.credentials

    def set(self, provider_id, credentials):
        self.saved = (provider_id, credentials)


def test_provider_yml_literal_key_wins_over_environment_and_profile(monkeypatch):
    provider_factory = object.__new__(NexusProviderFactory)
    provider_factory.loader = _Loader({"api_key": "yaml-key", "model": "test-model"})
    provider_factory._load_provider_instance = lambda _name: _Provider()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda *_args: "stale-profile-key")

    provider = provider_factory.get_provider_by_name("cloud", "deepseek")

    assert provider.api_key == "yaml-key"
    assert provider.headers["Authorization"] == "Bearer yaml-key"
    assert provider._credential_id == "config:deepseek"
    assert "yaml-key" not in provider._credential_id


def test_provider_yml_env_reference_is_supported(monkeypatch):
    provider_factory = object.__new__(NexusProviderFactory)
    provider_factory.loader = _EnvLoader()
    provider_factory._load_provider_instance = lambda _name: _Provider()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "expanded-key")
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda *_args: "stale-profile-key")

    provider = provider_factory.get_provider_by_name("cloud", "deepseek")

    assert provider.api_key == "expanded-key"
    assert provider.headers["Authorization"] == "Bearer expanded-key"
    assert provider._credential_id == "env:deepseek"
    assert "expanded-key" not in provider._credential_id


def test_named_profile_credential_identity_is_opaque(monkeypatch):
    provider_factory = object.__new__(NexusProviderFactory)
    provider_factory.loader = _Loader({"model": "test-model"})
    provider_factory._load_provider_instance = lambda _name: _Provider()
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda *_args: "profile-secret")

    provider = provider_factory.get_provider_by_name("cloud", "deepseek", profile="backup")

    assert provider.api_key == "profile-secret"
    assert provider._credential_id == "profile:deepseek:backup"
    assert provider._credential_source == "profile"
    assert "profile-secret" not in provider._credential_id


def test_named_profile_acquires_exclusive_runtime_lease(monkeypatch, tmp_path):
    from models.providers.core.profiles import ProviderProfile, ProviderProfileStore

    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(
        name="backup", provider="deepseek", type="api_key", api_key="profile-secret",
    ))
    provider_factory = object.__new__(NexusProviderFactory)
    provider_factory.loader = _Loader({"model": "test-model"})
    provider_factory._load_provider_instance = lambda _name: _Provider()
    monkeypatch.setattr(factory_module, "_resolve_api_key", lambda *_args: "profile-secret")
    monkeypatch.setattr("models.providers.core.profiles.load_profile_store", lambda: ProviderProfileStore(tmp_path / "profiles.json"))

    provider = provider_factory.get_provider_by_name("cloud", "deepseek", profile="backup")

    assert provider is not None
    assert provider._profile_lease is not None
    assert ProviderProfileStore(tmp_path / "profiles.json").acquire_lease(
        "deepseek", "backup", owner_id="other", ttl_seconds=10,
    ) is None
    assert provider._profile_store.release_lease(provider._profile_lease) is True


def test_provider_initialization_failure_does_not_silently_switch_provider():
    provider_factory = object.__new__(NexusProviderFactory)
    provider_factory.loader = _Loader({})

    def fail(_name):
        raise ImportError("provider package unavailable")

    provider_factory._load_provider_instance = fail

    assert provider_factory.get_provider_by_name("cloud", "anthropic") is None
    assert provider_factory.resolve_with_fallback("anthropic", attempt=1) is None


def test_expired_oauth_refresh_failure_does_not_return_stale_token(monkeypatch):
    class BrokenOAuthProvider:
        async def refresh_token(self, _credentials):
            raise RuntimeError("refresh failed")

        def get_api_key(self, credentials):
            return credentials.access

    calls = {"registered": False}
    store = _Store(OAuthCredentials(access="expired-access", refresh="refresh", expires=1.0))
    monkeypatch.setattr("models.providers.core.profiles.resolve_api_key", lambda *_args: None)
    monkeypatch.setattr(
        "models.providers.auth.oauth.providers.autoregister.register_all_oauth_providers",
        lambda: calls.__setitem__("registered", True),
    )
    monkeypatch.setattr("models.providers.auth.oauth.storage.load_oauth_token_store", lambda: store)
    monkeypatch.setattr("models.providers.auth.oauth.registry.get_oauth_provider", lambda _provider_id: BrokenOAuthProvider())

    key = factory_module._resolve_api_key("codex")

    assert calls["registered"] is True
    assert key is None
    assert store.saved is None
