from types import SimpleNamespace


def test_list_hives_exposes_partial_worker_failure(monkeypatch):
    import server

    live = {
        "a-success": SimpleNamespace(status="success"),
        "a-failed": SimpleNamespace(status="failed"),
    }
    engine = SimpleNamespace(
        list_personas=lambda: {"WORKER": "General worker"},
        get_agent=lambda identifier: live.get(identifier),
    )
    monkeypatch.setattr(server, "_get_hive_engine", lambda: engine)
    monkeypatch.setattr(server, "_persist_hive_manifest", lambda: None)
    monkeypatch.setattr(
        server,
        "_HIVES",
        {
            "hive-partial": {
                "id": "hive-partial",
                "status": "running",
                "agents": [
                    {"id": "a-success", "status": "running"},
                    {"id": "a-failed", "status": "running"},
                ],
            }
        },
    )

    result = server.list_hives()
    hive = result["hives"][0]
    assert hive["status"] == "failed"
    assert hive["partial"] is True
    assert [agent["status"] for agent in hive["agents"]] == ["success", "failed"]
