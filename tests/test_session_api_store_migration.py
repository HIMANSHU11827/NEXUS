"""Regression coverage for API session writers using the shared store."""

import json
import importlib
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from nexus.session_store import atomic_write_json, session_write_lock


def _configure_session_module(module_name, tmp_path, monkeypatch):
    module = importlib.import_module(module_name)
    if module_name == "server":
        monkeypatch.setattr(module, "_SESSION_DIR", str(tmp_path))
    else:
        monkeypatch.setattr(module, "_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_LOOPS", {})
    return module


def test_server_clear_session_uses_atomic_store_and_updates_cached_loop(tmp_path, monkeypatch):
    import server

    class CachedLoop:
        def __init__(self):
            self.memory = [{"role": "user", "content": "old"}]
            self.save_called = False

        def save_memory(self):  # pragma: no cover - should not be reached
            self.save_called = True

    monkeypatch.setattr(server, "_SESSION_DIR", str(tmp_path))
    cached = CachedLoop()
    monkeypatch.setattr(server, "_LOOPS", {"session_a": cached})

    assert server._clear_session_files("session_a") is True
    assert json.loads((tmp_path / "session_a.json").read_text(encoding="utf-8")) == []
    assert json.loads((tmp_path / "session_a.meta").read_text(encoding="utf-8")) == {"title": "New Chat"}
    assert cached.memory == []
    assert cached.save_called is False


def test_server_title_writer_uses_session_lock_and_atomic_json(tmp_path):
    import server

    meta_path = tmp_path / "session_a.meta"
    server._write_session_title_sync(str(meta_path), "Renamed")

    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"title": "Renamed"}
    assert not list(tmp_path.glob(".session-meta-*.tmp"))


def test_gui_clear_session_uses_atomic_store_and_updates_cached_loop(tmp_path, monkeypatch):
    import gui.api as gui_api

    class CachedLoop:
        def __init__(self):
            self.memory = [{"role": "assistant", "content": "old"}]

    monkeypatch.setattr(gui_api, "_ROOT", str(tmp_path))
    monkeypatch.setattr(gui_api, "_LOOPS", {"session_a": CachedLoop()})

    assert gui_api._clear_session_files("session_a") is True
    sessions = tmp_path / "logs" / "sessions"
    assert json.loads((sessions / "session_a.json").read_text(encoding="utf-8")) == []
    assert json.loads((sessions / "session_a.meta").read_text(encoding="utf-8")) == {"title": "New Chat"}
    assert gui_api._LOOPS["session_a"].memory == []


def test_gui_title_writer_uses_shared_store(tmp_path):
    import gui.api as gui_api

    meta_path = tmp_path / "session_a.meta"
    gui_api._write_session_title_sync(str(meta_path), "Renamed")

    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"title": "Renamed"}
    assert not list(tmp_path.glob(".session-meta-*.tmp"))


@pytest.mark.parametrize("module_name", ["server", "gui.api"])
def test_non_default_delete_removes_transcript_metadata_and_cached_loop(
    module_name, tmp_path, monkeypatch
):
    module = _configure_session_module(module_name, tmp_path, monkeypatch)
    session_id = "delete_me"
    path = Path(module.session_file_path(session_id))
    meta_path = Path(module.session_file_path(session_id, ".meta"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"role": "user", "content": "old"}]', encoding="utf-8")
    meta_path.write_text('{"title": "Old"}', encoding="utf-8")
    module._LOOPS[session_id] = object()

    assert module._delete_session_files(session_id) is True
    assert not path.exists()
    assert not meta_path.exists()
    assert session_id not in module._LOOPS


@pytest.mark.parametrize("module_name", ["server", "gui.api"])
def test_non_default_delete_waits_for_inflight_shared_store_write(
    module_name, tmp_path, monkeypatch
):
    module = _configure_session_module(module_name, tmp_path, monkeypatch)
    session_id = "racing_session"
    path = module.session_file_path(session_id)
    writer_holds_lock = threading.Event()
    release_writer = threading.Event()
    delete_started = threading.Event()
    delete_results = []

    def writer():
        with session_write_lock(path):
            atomic_write_json(path, [{"role": "assistant", "content": "in flight"}])
            writer_holds_lock.set()
            assert release_writer.wait(timeout=5)

    def deleter():
        delete_started.set()
        delete_results.append(module._delete_session_files(session_id))

    writer_thread = threading.Thread(target=writer)
    delete_thread = threading.Thread(target=deleter)
    writer_thread.start()
    assert writer_holds_lock.wait(timeout=5)
    delete_thread.start()
    assert delete_started.wait(timeout=5)
    assert delete_thread.is_alive()

    release_writer.set()
    writer_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert not delete_thread.is_alive()
    assert delete_results == [True]
    assert not Path(path).exists()


@pytest.mark.parametrize("module_name", ["server", "gui.api"])
def test_default_clear_checks_existence_after_acquiring_shared_lock(
    module_name, tmp_path, monkeypatch
):
    module = _configure_session_module(module_name, tmp_path, monkeypatch)
    session_id = "default"
    path = module.session_file_path(session_id)
    writer_holds_lock = threading.Event()
    allow_writer_to_persist = threading.Event()
    clear_attempted_lock = threading.Event()
    clear_results = []
    real_session_write_lock = module.session_write_lock

    @contextmanager
    def observed_session_write_lock(lock_path):
        clear_attempted_lock.set()
        with real_session_write_lock(lock_path):
            yield

    monkeypatch.setattr(module, "session_write_lock", observed_session_write_lock)

    def writer():
        with session_write_lock(path):
            writer_holds_lock.set()
            assert allow_writer_to_persist.wait(timeout=5)
            atomic_write_json(path, [{"role": "user", "content": "created concurrently"}])

    def clearer():
        clear_results.append(module._clear_session_files(session_id))

    writer_thread = threading.Thread(target=writer)
    clear_thread = threading.Thread(target=clearer)
    writer_thread.start()
    assert writer_holds_lock.wait(timeout=5)
    clear_thread.start()
    assert clear_attempted_lock.wait(timeout=5)

    allow_writer_to_persist.set()
    writer_thread.join(timeout=5)
    clear_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert not clear_thread.is_alive()
    assert clear_results == [True]
    assert json.loads(Path(path).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("module_name", ["server", "gui.api"])
def test_non_default_delete_cleans_orphaned_metadata(module_name, tmp_path, monkeypatch):
    module = _configure_session_module(module_name, tmp_path, monkeypatch)
    session_id = "metadata_only"
    meta_path = Path(module.session_file_path(session_id, ".meta"))
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text('{"title": "Orphan"}', encoding="utf-8")

    response = module.delete_session(session_id)

    assert response["status"] == "success"
    assert response["deleted"] is True
    assert not meta_path.exists()


def test_default_delete_semantics_remain_clear_not_remove(tmp_path, monkeypatch):
    for module_name in ("server", "gui.api"):
        module_root = tmp_path / module_name.replace(".", "_")
        module = _configure_session_module(module_name, module_root, monkeypatch)
        path = Path(module.session_file_path("default"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[{"role": "user", "content": "old"}]', encoding="utf-8")

        response = module.delete_session("default")

        assert response["status"] == "success"
        assert response["cleared"] is True
        assert response.get("deleted") is not True
        assert json.loads(path.read_text(encoding="utf-8")) == []
        assert json.loads(
            Path(module.session_file_path("default", ".meta")).read_text(encoding="utf-8")
        ) == {"title": "New Chat"}


def test_api_session_modules_import_shared_store():
    for module_path in (Path("server/__init__.py"), Path("gui/api.py")):
        source = module_path.read_text(encoding="utf-8")
        assert "from nexus.session_store import atomic_write_json, session_write_lock" in source
