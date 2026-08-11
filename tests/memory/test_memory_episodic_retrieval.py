"""Regression tests for query-aware episodic memory retrieval."""

import json
import time

from memory import MemoryManager


def test_prefetch_episodic_prefers_query_match_over_unrelated_recent_failure(tmp_path):
    """A relevant episode must not be displaced by a globally high failure score."""
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir()
    now = time.time()
    entries = [
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "input": "database migration timeout",
            "success": False,
            "n_failed": 2,
            "error": "database connection failed",
        },
        {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(now - 86400)
            ),
            "input": "deploy rollback to the previous release",
            "success": True,
            "n_failed": 0,
            "plan_steps": 2,
        },
    ]
    with (replay_dir / "replays.jsonl").open("w", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(json.dumps(entry) + "\n")

    manager = MemoryManager(str(tmp_path), session_id="episodic-query")
    selected = manager._prefetch_episodic(
        limit=1, user_message="How do I deploy rollback safely?"
    )

    assert len(selected) == 1
    assert selected[0]["input"] == "deploy rollback to the previous release"
    assert "deploy rollback" in manager.get("episodic")


def test_prefetch_all_passes_user_message_to_episodic_retrieval(tmp_path, monkeypatch):
    """The live prefetch pipeline must provide the query to episodic ranking."""
    manager = MemoryManager(str(tmp_path), session_id="episodic-query")
    captured = {}

    def fake_prefetch(*, user_message="", limit=5):
        captured["user_message"] = user_message
        return []

    monkeypatch.setattr(manager, "_prefetch_episodic", fake_prefetch)
    # Stub the unrelated channels so this test remains about episodic wiring.
    monkeypatch.setattr(manager, "_prefetch_session", lambda _message: "")
    monkeypatch.setattr(manager, "_prefetch_rag", lambda _message: "")
    monkeypatch.setattr(manager, "_prefetch_failures", lambda _message: "")
    monkeypatch.setattr(manager, "_prefetch_knowledge", lambda _message: "")
    monkeypatch.setattr(manager, "_prefetch_procedural", lambda _message: "")

    import asyncio

    asyncio.run(manager.prefetch_all("deploy rollback"))
    assert captured["user_message"] == "deploy rollback"
