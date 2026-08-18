import json

import pytest

import nexus.common.engine_manager as engine_manager


def test_engine_config_persists_atomically_and_preserves_shape(tmp_path, monkeypatch):
    config_path = tmp_path / "configure" / "engine.json"
    status_path = tmp_path / ".nexus" / "status.json"
    monkeypatch.setattr(engine_manager, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(engine_manager, "STATUS_PATH", str(status_path))

    engine_manager.save_config({"default_model": "model.gguf", "system": {"threads": 4}})
    loaded = engine_manager.load_or_create_config()

    assert loaded["default_model"] == "model.gguf"
    assert loaded["system"] == {"threads": 4}
    assert loaded["llama_cpp_params"] == {}
    assert json.loads(config_path.read_text(encoding="utf-8"))["default_model"] == "model.gguf"


def test_reload_engine_never_claims_missing_model_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_manager, "_CONFIG_PATH", str(tmp_path / "engine.json"))
    monkeypatch.setattr(engine_manager, "STATUS_PATH", str(tmp_path / "status.json"))

    result = engine_manager.reload_engine(str(tmp_path / "missing.gguf"))

    assert result["status"] == "not_ready"
    assert result["compiled"] is False
    assert result["reason"] == "model_artifact_missing"
    assert engine_manager.get_engine_status()["status"] == "not_ready"


def test_reload_engine_records_existing_model_as_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_manager, "_CONFIG_PATH", str(tmp_path / "engine.json"))
    monkeypatch.setattr(engine_manager, "STATUS_PATH", str(tmp_path / "status.json"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")

    result = engine_manager.reload_engine(str(model))

    assert result["status"] == "ready"
    assert result["compiled"] is True
    assert engine_manager.get_engine_status()["model_path"] == str(model.resolve())


def test_compiler_reports_unavailable_instead_of_fake_success():
    from nexus.common.engine_compiler import compile_llama_cpp

    assert compile_llama_cpp()["status"] == "unavailable"


def test_engine_reload_path_is_contained_in_local_model_directory(tmp_path, monkeypatch):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    local_root = tmp_path / "models" / "local"
    local_root.mkdir(parents=True)
    model = local_root / "model.gguf"
    model.write_bytes(b"model")

    assert server._resolve_local_model_path("model.gguf") == str(model.resolve())
    assert server._resolve_local_model_path(str(model)) == str(model.resolve())


def test_engine_reload_path_rejects_traversal_and_external_absolute_paths(tmp_path, monkeypatch):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "models" / "local").mkdir(parents=True)

    with pytest.raises(Exception) as traversal:
        server._resolve_local_model_path("..\\outside.gguf")
    assert getattr(traversal.value, "status_code", None) == 403

    with pytest.raises(Exception) as absolute:
        server._resolve_local_model_path(str(tmp_path / "outside.gguf"))
    assert getattr(absolute.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_engine_reload_endpoint_preserves_path_boundary_status(tmp_path, monkeypatch):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "models" / "local").mkdir(parents=True)

    class Request:
        async def json(self):
            return {"model": "..\\outside.gguf"}

    with pytest.raises(Exception) as raised:
        await server.reload_local_engine(Request())
    assert getattr(raised.value, "status_code", None) == 403
