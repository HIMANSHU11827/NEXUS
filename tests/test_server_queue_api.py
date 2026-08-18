from queues.store import TaskQueue


def test_queue_snapshot_is_session_scoped_and_does_not_expose_lease_tokens(monkeypatch, tmp_path):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    queue = TaskQueue(root=str(tmp_path))
    session_task = queue.enqueue(
        "continue session work api_key=top-secret-value",
        session_id="session-a",
    )
    global_task = queue.enqueue("run scheduled work", idempotency_key="cron:test:1")
    leased = queue.lease(timeout_sec=30, worker_id="test")
    assert leased and leased["id"] in {session_task, global_task}

    snapshot = server.queue_snapshot(session_id="session-a", include_global=True, limit=20)
    ids = {item["id"] for item in snapshot["tasks"]}
    assert session_task in ids
    assert global_task in ids
    assert all("lease_token" not in item for item in snapshot["tasks"])
    assert all("top-secret-value" not in item["summary"] for item in snapshot["tasks"])

    scoped = server.queue_snapshot(session_id="session-a", include_global=False, limit=20)
    assert {item["id"] for item in scoped["tasks"]} == {session_task}


def test_queue_snapshot_reports_worker_mode_without_claiming_external_worker(monkeypatch, tmp_path):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_EMBED_QUEUE_DRIVER", raising=False)
    snapshot = server.queue_snapshot(limit=5)
    assert snapshot["mode"] == "embedded"
    assert snapshot["worker"] == "stopped"
    assert snapshot["states"]["queued"] == 0


def test_queue_snapshot_external_mode_when_explicitly_disabled(monkeypatch, tmp_path):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("NEXUS_EMBED_QUEUE_DRIVER", "false")
    snapshot = server.queue_snapshot(limit=5)
    assert snapshot["mode"] == "external"
    assert snapshot["worker"] == "external"
    assert snapshot["states"]["queued"] == 0
