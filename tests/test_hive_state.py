import pytest
import threading

from hive.engine import NexusHiveEngine
from hive.state import HiveStateConflict, HiveStateStore


def test_blackboard_persists_with_optimistic_versions(tmp_path):
    first = NexusHiveEngine(str(tmp_path))
    record = first.post_to_blackboard("finding", {"answer": 42}, writer="agent-a")
    assert record["version"] == 1

    second = NexusHiveEngine(str(tmp_path))
    assert second.get_live_signals()["finding"] == {"answer": 42}
    snapshot = second.get_blackboard_snapshot()["finding"]
    assert snapshot["version"] == 1
    assert snapshot["writer"] == "agent-a"

    updated = second.post_to_blackboard("finding", "revised", expected_version=1, writer="agent-b")
    assert updated["version"] == 2
    with pytest.raises(HiveStateConflict):
        first.post_to_blackboard("finding", "stale", expected_version=1, writer="agent-c")


def test_artifact_manifest_reconciles_present_changed_and_missing(tmp_path):
    artifact = tmp_path / "workspace" / "hive" / "answer.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("original", encoding="utf-8")
    store = HiveStateStore(str(tmp_path))
    created = store.register_artifact(str(artifact), hive_id="hive-1", agent_id="agent-1")

    assert created["status"] == "present"
    assert store.reconcile_artifacts("hive-1")[0]["status"] == "present"

    artifact.write_text("changed", encoding="utf-8")
    changed = store.reconcile_artifacts("hive-1")[0]
    assert changed["status"] == "changed"
    artifact.unlink()
    missing = store.reconcile_artifacts("hive-1")[0]
    assert missing["status"] == "missing"


def test_artifact_registration_rejects_paths_outside_root(tmp_path):
    store = HiveStateStore(str(tmp_path))
    outside = tmp_path.parent / "outside-artifact.txt"
    outside.write_text("no", encoding="utf-8")
    try:
        with pytest.raises(ValueError):
            store.register_artifact(str(outside))
    finally:
        outside.unlink(missing_ok=True)


def test_artifact_registration_rejects_symlink_escape(tmp_path):
    store = HiveStateStore(str(tmp_path))
    outside = tmp_path.parent / "outside-symlink-artifact.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "linked-artifact.txt"
    try:
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation is unavailable on this platform")
        with pytest.raises(ValueError):
            store.register_artifact(str(link))
    finally:
        link.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def test_blackboard_concurrent_writers_preserve_versions(tmp_path):
    store = HiveStateStore(str(tmp_path))
    barrier = threading.Barrier(2)
    results = []

    def write(value):
        barrier.wait()
        try:
            results.append(store.put_blackboard("shared", value, expected_version=0))
        except HiveStateConflict:
            results.append("conflict")

    threads = [threading.Thread(target=write, args=(value,)) for value in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(result == "conflict" for result in results) == [False, True]
    snapshot = store.get_blackboard()["shared"]
    assert snapshot["version"] == 1
