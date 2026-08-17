"""Voice API must not expose internal exception text to clients."""

import sys
import types

from fastapi.testclient import TestClient

import authentication
import server


def _client(monkeypatch):
    token = "voice-error-test-token"
    monkeypatch.setattr(authentication, "_AUTH_TOKEN", token)
    client = TestClient(server.app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_voice_status_returns_public_error_only(monkeypatch):
    secret_error = "provider failed at C:\\Users\\alice\\secret\" sk-live-voice"
    monkeypatch.setattr(server, "_get_voice_assistant", lambda _session: (_ for _ in ()).throw(RuntimeError(secret_error)))

    with _client(monkeypatch) as client:
        response = client.get("/api/voice/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["message"] == "Voice status unavailable"
    assert secret_error not in response.text
    assert "sk-live-voice" not in response.text


def test_voice_transcription_returns_public_error_only(monkeypatch):
    secret_error = "TLS failure at C:\\private\\token=sk-live-transcribe"
    monkeypatch.setattr(server, "_get_voice_assistant", lambda _session: (_ for _ in ()).throw(RuntimeError(secret_error)))

    with _client(monkeypatch) as client:
        response = client.post("/api/voice/transcribe", json={})

    assert response.status_code == 500
    assert response.json()["detail"] == "Voice transcription unavailable"
    assert secret_error not in response.text
    assert "sk-live-transcribe" not in response.text


def test_live_voice_settings_handler_persists_allowlisted_values(monkeypatch):
    class Settings:
        auto_speak = False
        voice_name = "default"
        whisper_language = "en"
        volume = 1.0
        speech_speed = 1.0

    class Assistant:
        settings = Settings()

    persisted = []
    monkeypatch.setattr(server, "_get_voice_assistant", lambda _session: Assistant())
    monkeypatch.setattr(server, "_persist_voice_settings", lambda values: persisted.append(dict(values)))

    with _client(monkeypatch) as client:
        response = client.post(
            "/api/voice/settings",
            json={"session_id": "s", "auto_speak": True, "voice_name": "nexus", "secret": "discard"},
        )

    assert response.status_code == 200
    assert response.json()["settings"]["auto_speak"] is True
    assert persisted and persisted[0]["secret"] == "discard"


def test_voice_persistence_allowlists_settings(monkeypatch):
    created = []

    class FakeLoader:
        def __init__(self):
            self.saved = None
            created.append(self)

        def get(self, _key, default):
            return {"voice_name": "old"}

        def set(self, key, value):
            self.saved = (key, value)

        def save(self):
            return None

    monkeypatch.setattr("configure.config_loader.NexusConfigLoader", FakeLoader)
    server._persist_voice_settings({"auto_speak": True, "secret": "discard"})

    # The helper only forwards known voice settings to the persisted mapping.
    assert created[-1].saved == ("voice", {"voice_name": "old", "auto_speak": True})


def test_legacy_voice_statistics_returns_public_error_only(monkeypatch):
    secret_error = "provider path=C:\\private\\voice.json token=sk-live-legacy"

    class FailingAssistant:
        @classmethod
        def from_config(cls, _config):
            raise RuntimeError(secret_error)

    fake_voice = types.ModuleType("voice")
    fake_voice.VoiceAssistant = FailingAssistant
    monkeypatch.setitem(sys.modules, "voice", fake_voice)

    payload = server.get_voice_statistics()

    assert payload == {"status": "error", "message": "Voice statistics unavailable"}
    assert secret_error not in str(payload)
