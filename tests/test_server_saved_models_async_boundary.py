import asyncio


def test_saved_model_listing_can_run_off_event_loop(tmp_path, monkeypatch):
    import apps.api as server

    config = tmp_path / "provider.yml"
    config.write_text("providers: {}\n", encoding="utf-8")
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "yaml", object())

    result = asyncio.run(asyncio.to_thread(server._list_saved_models_sync))

    assert result == {"models": []}
