import apps.api


def test_verification_recipe_endpoint_is_read_only_and_workspace_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    result = server.get_verification_recipe()
    assert result["root"] == str(tmp_path.resolve())
    assert result["recipe"]["kind"] == "python"


def test_verification_recipe_endpoint_rejects_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    try:
        server.get_verification_recipe(str(tmp_path.parent))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("outside recipe root was accepted")
