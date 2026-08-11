import multiprocessing
import time
from pathlib import Path

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


def test_record_failure_cools_without_permanently_disabling(tmp_path):
    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))
    store.add_profile(ProviderProfile(name="backup", provider="demo", type="api_key", api_key="y"))
    store.record_failure("demo", "main", reason="rate_limit")
    main = next(p for p in store.list_profiles("demo") if p.name == "main")
    assert main.active is True
    assert main.cooldown_until > 0
    assert store.next_profile("demo", "main").name == "backup"


def test_record_success_clears_cooldown(tmp_path):
    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))
    store.record_failure("demo", "main", reason="rate_limit")
    store.record_success("demo", "main")
    main = store.get_profile("demo", "main")
    assert main.cooldown_until == 0
    assert main.cooldown_reason == ""
    assert main.error_count == 0


def test_cross_process_lease_is_exclusive_and_releases(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))
    stale_store = ProviderProfileStore(path)

    first = store.acquire_lease("demo", owner_id="worker-a", ttl_seconds=10)
    assert first is not None
    stale_store.add_profile(ProviderProfile(name="backup", provider="demo", type="api_key", api_key="y"))
    contender = ProviderProfileStore(path).acquire_lease("demo", owner_id="worker-b", ttl_seconds=10)
    assert contender is not None
    assert contender.profile == "backup"
    assert ProviderProfileStore(path).release_lease(contender) is True

    assert ProviderProfileStore(path).release_lease(first) is True
    second = ProviderProfileStore(path).acquire_lease("demo", owner_id="worker-b", ttl_seconds=10)
    assert second is not None
    assert second.profile == "main"


def test_stale_profile_stores_merge_mutations_under_file_lock(tmp_path):
    path = tmp_path / "profiles.json"
    first = ProviderProfileStore(path)
    first.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))
    stale = ProviderProfileStore(path)

    first.add_profile(ProviderProfile(name="first", provider="demo", type="api_key", api_key="a"))
    stale.add_profile(ProviderProfile(name="second", provider="demo", type="api_key", api_key="b"))

    names = {profile.name for profile in ProviderProfileStore(path).list_profiles("demo")}
    assert names == {"main", "first", "second"}


def test_lease_expiry_allows_recovery_without_release(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))

    first = store.acquire_lease("demo", owner_id="crashed-worker", ttl_seconds=1)
    assert first is not None
    time.sleep(1.05)
    recovered = ProviderProfileStore(path).acquire_lease("demo", owner_id="recovery-worker", ttl_seconds=10)
    assert recovered is not None
    assert recovered.lease_id != first.lease_id


def test_lease_token_and_owner_are_required_for_release(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="secret"))

    lease = store.acquire_lease("demo", owner_id="owner-a", ttl_seconds=10)
    assert lease is not None
    assert ProviderProfileStore(path).release_lease(lease.__class__(
        provider=lease.provider,
        profile=lease.profile,
        lease_id=lease.lease_id,
        owner_id="owner-b",
        expires_at=lease.expires_at,
    )) is False
    assert ProviderProfileStore(path).acquire_lease("demo", owner_id="owner-b", ttl_seconds=10) is None


def _lease_worker(path_str, ready, output):
    ready.wait(10)
    lease = ProviderProfileStore(Path(path_str)).acquire_lease("demo", ttl_seconds=10)
    output.put(lease.lease_id if lease else None)


def test_lease_race_across_processes_allows_only_one_winner(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    output = context.Queue()
    workers = [context.Process(target=_lease_worker, args=(str(path), ready, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    ready.set()
    results = [output.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    assert sum(result is not None for result in results) == 1


def test_profile_save_uses_unique_same_directory_temp_path(tmp_path, monkeypatch):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="demo", type="api_key", api_key="x"))

    observed = []
    original_replace = Path.replace

    def record_replace(self, target):
        if self.parent == path.parent and self != path:
            observed.append(self.name)
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    store.add_profile(ProviderProfile(name="backup", provider="demo", type="api_key", api_key="y"))

    assert len(observed) == 1
    assert observed[0].startswith(".profiles.json.")
    assert observed[0].endswith(".tmp")
    assert not list(tmp_path.glob("*.tmp"))
