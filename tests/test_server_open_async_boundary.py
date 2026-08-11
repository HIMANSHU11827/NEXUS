import asyncio


def test_open_path_platform_launcher_runs_in_worker(monkeypatch, tmp_path):
    import server

    opened = []
    monkeypatch.setattr(server.os, "startfile", lambda path: opened.append(path), raising=False)
    asyncio.run(asyncio.to_thread(server._open_path_sync, str(tmp_path)))

    assert opened == [str(tmp_path)]
