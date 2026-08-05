from providers.profiles import ProviderProfile, ProviderProfileStore


def test_profile_selection_ignores_disabled_and_cooling_credentials(tmp_path):
    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(name="disabled", provider="demo", type="api_key", api_key="x", enabled=False))
    store.add_profile(ProviderProfile(name="cooling", provider="demo", type="api_key", api_key="y", cooldown_until=10**12))
    store.add_profile(ProviderProfile(name="eligible", provider="demo", type="api_key", api_key="z", model_id="native-model", model_alias="Friendly model"))

    selected = store.get_profile("demo")
    assert selected is not None
    assert selected.name == "eligible"
    assert selected.model_id == "native-model"
    assert selected.model_alias == "Friendly model"
    assert store.get_api_key("demo") == "z"
    assert store.get_profile("demo", "disabled") is None


def test_profile_store_supports_unlimited_named_profiles(tmp_path):
    store = ProviderProfileStore(tmp_path / "profiles.json")
    for index in range(12):
        store.add_profile(ProviderProfile(name=f"key-{index}", provider="demo", type="api_key", api_key=f"value-{index}"))
    assert store.count("demo") == 12
    assert {profile.name for profile in store.list_profiles("demo")} == {f"key-{i}" for i in range(12)}
