import os
import tempfile
from pathlib import Path

import pytest

from providers.oauth.storage import OAuthTokenStore
from providers.oauth.types import OAuthCredentials


class TestOAuthTokenStore:
    def test_store_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            c = OAuthCredentials(access="tok_abc", refresh="ref_xyz", expires=99999.0)
            store.set("test_provider", c)
            loaded = store.get("test_provider")
            assert loaded is not None
            assert loaded.access == "tok_abc"
            assert loaded.refresh == "ref_xyz"

    def test_store_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            assert store.get("nope") is None

    def test_delete_removes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            store.set("del_me", OAuthCredentials("a", "r", 1.0))
            assert store.delete("del_me") is True
            assert store.get("del_me") is None

    def test_delete_nonexistent_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            assert store.delete("ghost") is False

    def test_list_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            store.set("a", OAuthCredentials("a", "r", 1.0))
            store.set("b", OAuthCredentials("b", "r", 1.0))
            providers = store.list_providers()
            assert "a" in providers
            assert "b" in providers

    def test_clear_removes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OAuthTokenStore(Path(tmp) / "store.json")
            store.set("x", OAuthCredentials("a", "r", 1.0))
            store.clear()
            assert store.list_providers() == []

    def test_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oauth_store.json"
            store = OAuthTokenStore(path)
            store.set("persist", OAuthCredentials("a", "r", 999.0))
            # New instance reads same file
            store2 = OAuthTokenStore(path)
            loaded = store2.get("persist")
            assert loaded is not None
            assert loaded.access == "a"

    def test_stale_store_instances_merge_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oauth_store.json"
            first = OAuthTokenStore(path)
            stale = OAuthTokenStore(path)
            first.set("first", OAuthCredentials("a", "r", 999.0))
            stale.set("second", OAuthCredentials("b", "r", 999.0))
            assert set(OAuthTokenStore(path).list_providers()) == {"first", "second"}

    def test_store_file_is_written_with_private_permissions(self):
        if os.name == "nt":
            pytest.skip("POSIX permission bits are not reliable on Windows ACL filesystems")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oauth_store.json"
            store = OAuthTokenStore(path)
            store.set("persist", OAuthCredentials("a", "r", 999.0))

            mode = path.stat().st_mode & 0o777
            assert mode & 0o077 == 0
