"""Crash and concurrency regression tests for gateway lifecycle persistence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from gateways.state import GatewayStateStore


def test_state_store_round_trip_creates_durable_lock_sidecar(tmp_path):
    path = tmp_path / "gateway" / "state.json"
    store = GatewayStateStore(str(path))

    store.save({"telegram": {"state": "running", "restarts": 2}})

    assert store.load()["telegram"]["restarts"] == 2
    assert path.with_name("state.json.lock.sqlite3").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_state_store_serializes_concurrent_snapshots_without_corruption(tmp_path):
    store = GatewayStateStore(str(tmp_path / "state.json"))

    def write(index: int) -> None:
        store.save({"platform": {"attempt": index}})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(32)))

    persisted = store.load()
    assert persisted["platform"]["attempt"] in range(32)


def test_state_store_degrades_on_corrupt_snapshot(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not-json", encoding="utf-8")

    assert GatewayStateStore(str(path)).load() == {}
