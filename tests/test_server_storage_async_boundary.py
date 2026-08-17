import asyncio


def test_storage_cleanup_runs_in_worker_and_preserves_session_index(tmp_path):
    import apps.api

    sessions = tmp_path / "logs" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "old.json").write_text("old", encoding="utf-8")
    (sessions / "session_index.json").write_text("keep", encoding="utf-8")

    count = asyncio.run(asyncio.to_thread(server._clear_workspace_storage_sync, str(tmp_path), "sessions"))

    assert count == 1
    assert not (sessions / "old.json").exists()
    assert (sessions / "session_index.json").exists()
