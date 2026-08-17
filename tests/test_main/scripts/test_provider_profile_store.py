import os
from pathlib import Path

import pytest

from models.providers.core.profiles import ProviderProfile, ProviderProfileStore


def test_provider_profile_store_persists_and_reads_profile(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProviderProfileStore(path)

    store.add_profile(ProviderProfile(name="main", provider="deepseek", type="api_key", api_key="sk-test"))

    loaded = ProviderProfileStore(path).get_profile("deepseek", "main")
    assert loaded is not None
    assert loaded.api_key == "sk-test"


def test_provider_profile_store_file_is_private_on_posix(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not reliable on Windows ACL filesystems")

    path = Path(tmp_path) / "profiles.json"
    store = ProviderProfileStore(path)
    store.add_profile(ProviderProfile(name="main", provider="deepseek", type="api_key", api_key="sk-test"))

    mode = path.stat().st_mode & 0o777
    assert mode & 0o077 == 0
