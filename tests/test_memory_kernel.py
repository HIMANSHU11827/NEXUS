"""
Tests for core.neural.memory_kernel — init hardening, fallback, and basic operations.
"""

import os
import sys
import tempfile
import threading

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from neural.memory_kernel import MemoryKernel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_kernel():
    """Reset the singleton before every test so state is fresh."""
    MemoryKernel.reset()
    yield
    MemoryKernel.reset()


@pytest.fixture
def tmp_root() -> str:
    """A temporary directory to use as the kernel root."""
    with tempfile.TemporaryDirectory(prefix="nexus_test_") as d:
        yield d


# ---------------------------------------------------------------------------
# Init & singleton behaviour
# ---------------------------------------------------------------------------

class TestInit:
    def test_basic_init(self, tmp_root):
        """Kernel initialises without error and creates the DB file."""
        mk = MemoryKernel(tmp_root)
        assert mk is not None
        assert mk._initialized
        assert mk.root == os.path.abspath(tmp_root)
        # DB file should exist under core/neural/
        expected_db = os.path.join(tmp_root, "core", "neural", "synapse.db")
        assert os.path.isfile(expected_db), f"DB not created at {expected_db}"

    def test_singleton_returns_same_instance(self, tmp_root):
        """Multiple calls return the same singleton instance."""
        a = MemoryKernel(tmp_root)
        b = MemoryKernel(tmp_root)
        assert a is b

    def test_singleton_with_different_root_ignores_second_arg(self, tmp_root):
        """Second call with a different root_dir is ignored (singleton)."""
        a = MemoryKernel(tmp_root)
        b = MemoryKernel("/some/other/path")
        assert a is b
        # The root should be from the FIRST call
        assert a.root == os.path.abspath(tmp_root)

    def test_thread_safe_init(self, tmp_root):
        """Multiple threads calling MemoryKernel simultaneously don't double-init."""
        results = []
        errors = []

        def create_kernel():
            try:
                mk = MemoryKernel(tmp_root)
                results.append(mk)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_kernel) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 8
        # All should be the exact same instance
        assert all(r is results[0] for r in results)

    def test_validate_not_initialised(self):
        """validate() returns appropriate message when not yet initialised."""
        msg = MemoryKernel.validate()
        assert "Not initialised yet" in msg

    def test_validate_initialised(self, tmp_root):
        """validate() returns status info when kernel is initialised."""
        MemoryKernel(tmp_root)
        msg = MemoryKernel.validate()
        assert "db_exists=True" in msg
        assert "db_path" in msg

    def test_reset_allows_fresh_init(self, tmp_root):
        """reset() followed by a new call runs __init__ again."""
        a = MemoryKernel(tmp_root)
        assert a._initialized
        MemoryKernel.reset()
        # After reset, a should be different from b because the singleton
        # was nuked.  BUT the old reference *a* still points at the old instance.
        # A new call creates a brand-new singleton.
        b = MemoryKernel(tmp_root)
        assert a is not b
        # Both should still be properly initialised
        assert a._initialized
        assert b._initialized


# ---------------------------------------------------------------------------
# Storage fallback
# ---------------------------------------------------------------------------

class TestStorageFallback:
    def test_fallback_on_readonly_dir(self):
        """Kernel falls back to tempdir when primary storage is not writable."""
        # Use a path inside a non-existent read-only area: the Windows
        # system32\drivers\etc directory exists but is typically not
        # writable by normal users.  If it IS writable (admin), we fall
        # back to a second strategy.
        readonly_candidate = os.path.join(
            os.environ.get("SystemRoot", "C:\\Windows"),
            "system32",
            "drivers",
            "etc",
        )
        if not os.path.isdir(readonly_candidate):
            pytest.skip("Read-only candidate path does not exist")

        try:
            probe = os.path.join(readonly_candidate, ".nexus_write_probe")
            with open(probe, "w") as _:
                os.remove(probe)
            pytest.skip("Read-only candidate is actually writable (running as admin)")
        except (OSError, PermissionError):
            pass

        mk = MemoryKernel(readonly_candidate)
        # The db_path should now point into %TEMP%
        assert "nexus_memory_kernel" in mk.db_path
        assert os.path.isfile(mk.db_path), f"Fallback DB not created at {mk.db_path}"
        assert mk._initialized

    def test_fallback_after_created_db_inaccessible(self):
        """Kernel handles the case where parent dir creation might fail gracefully."""
        with tempfile.TemporaryDirectory(prefix="nexus_fallback_") as d:
            # Create a path under the tempdir
            bogus = os.path.join(d, "nonexistent", "subdir", "also_missing")
            mk = MemoryKernel(bogus)
            # It should succeed (either at the requested path or via fallback)
            assert mk._initialized
            assert os.path.isfile(mk.db_path)
            # The kernel should have initialized successfully regardless
            assert mk.db_path is not None


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

class TestWorkingMemory:
    def test_store_and_recall(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.ram_store("test_key", 42)
        assert mk.ram_recall("test_key") == 42

    def test_recall_missing(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        assert mk.ram_recall("nonexistent") is None

    def test_ram_dump_empty(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        assert "Empty" in mk.ram_dump()

    def test_ram_dump_content(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.ram_store("foo", "bar")
        dump = mk.ram_dump()
        assert "foo" in dump
        assert "bar" in dump

    def test_overwrite_key(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.ram_store("k", "v1")
        mk.ram_store("k", "v2")
        assert mk.ram_recall("k") == "v2"


class TestEpisodicMemory:
    def test_log_and_list_episode(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.log_episode("sess_1", "Test Title", "A summary", "Some content")
        episodes = mk.list_episodes(session_id="sess_1")
        assert len(episodes) == 1
        assert episodes[0]["title"] == "Test Title"
        assert episodes[0]["summary"] == "A summary"

    def test_list_episodes_limit(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        for i in range(5):
            mk.log_episode(f"sess_{i}", f"Title {i}", f"Summary {i}", f"Content {i}")
        all_eps = mk.list_episodes(limit=3)
        assert len(all_eps) <= 3

    def test_list_episodes_session_filter(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.log_episode("sess_a", "A", "Summary A", "Content A")
        mk.log_episode("sess_b", "B", "Summary B", "Content B")
        eps_a = mk.list_episodes(session_id="sess_a")
        assert len(eps_a) == 1
        assert eps_a[0]["title"] == "A"


class TestCognitiveFacts:
    def test_store_and_recall_fact(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.store_fact("user", "name", "Alice", importance=5)
        facts = mk.recall_facts("user")
        assert len(facts) >= 1
        assert facts[0]["attribute"] == "name"
        assert facts[0]["value"] == "Alice"

    def test_recall_facts_empty(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        assert mk.recall_facts("nonexistent") == []

    def test_fact_ordering(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.store_fact("server", "region", "us-east", importance=1)
        mk.store_fact("server", "region", "eu-west", importance=10)
        facts = mk.recall_facts("server")
        # Higher importance should come first
        assert facts[0]["importance"] == 10


class TestMentalTimeTravel:
    def test_simulate_future(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        result = mk.simulate_future("deploy", "history here")
        assert "SIMULATION" in result
        assert "deploy" in result

    def test_retrospective_review_empty(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        review = mk.retrospective_review("any")
        assert "No past episodes" in review

    def test_retrospective_review_with_episodes(self, tmp_root):
        mk = MemoryKernel(tmp_root)
        mk.log_episode("s1", "Fix bug", "Fixed the login bug", "...")
        review = mk.retrospective_review("fixing")
        assert "RETROSPECTION_INSIGHTS" in review
        assert "Fix bug" in review
