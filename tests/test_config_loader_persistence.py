import json


def test_config_loader_data_setter_and_save_round_trip(tmp_path, monkeypatch):
    import configure.config_loader as module

    monkeypatch.setattr(module, "_CONFIG_DIR", tmp_path)
    (tmp_path / "settings.yml").write_text("mode: safe\n", encoding="utf-8")
    (tmp_path / "model_tasks.json").write_text(
        json.dumps({"tasks": ["initial"]}), encoding="utf-8"
    )
    monkeypatch.setattr(module.NexusConfigLoader, "_instance", None)
    monkeypatch.setattr(module.NexusConfigLoader, "_cache", {})

    loader = module.NexusConfigLoader()
    data = loader.data
    data["settings"]["mode"] = "normal"
    data["model_tasks"]["tasks"].append("next")
    loader.data = data

    assert loader.save() is True
    loader.reload()
    assert loader.data["settings"]["mode"] == "normal"
    assert loader.data["model_tasks"]["tasks"] == ["initial", "next"]
    assert not list(tmp_path.glob("*.tmp"))
