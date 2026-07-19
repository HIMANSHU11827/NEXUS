import yaml
from fastapi.testclient import TestClient


def test_provider_config_uses_project_config_path_and_creates_file(tmp_path, monkeypatch):
    import gui.api as api

    monkeypatch.setattr(api, "_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "require_config_write_allowed", lambda _request: None)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/providers/configure",
            json={
                "name": "openrouter",
                "instance_id": "openrouter-main",
                "model": "openrouter/test",
                "api_key": "${OPENROUTER_API_KEY}",
            },
        )

    config_path = tmp_path / "config" / "nexus_config.yaml"
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert config_path.exists()
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    route = saved["providers"]["cloud"]["openrouter-main"]
    assert route["parent_provider"] == "openrouter"
    assert route["model"] == "openrouter/test"
    assert route["api_key"] == "${OPENROUTER_API_KEY}"


def test_provider_config_does_not_overwrite_key_with_mask_placeholder(tmp_path, monkeypatch):
    import gui.api as api

    monkeypatch.setattr(api, "_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "require_config_write_allowed", lambda _request: None)
    config_path = tmp_path / "config" / "nexus_config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "cloud": {
                        "openrouter-main": {
                            "active": True,
                            "parent_provider": "openrouter",
                            "api_key": "${OPENROUTER_API_KEY}",
                        }
                    },
                    "local": {},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with TestClient(api.app) as client:
        response = client.post(
            "/api/providers/configure",
            json={
                "name": "openrouter",
                "instance_id": "openrouter-main",
                "model": "openrouter/updated",
                "api_key": "********",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    route = saved["providers"]["cloud"]["openrouter-main"]
    assert route["api_key"] == "${OPENROUTER_API_KEY}"
    assert route["model"] == "openrouter/updated"
