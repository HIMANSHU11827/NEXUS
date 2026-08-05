"""Tests for the redesigned NEXUS voice pipeline.

These tests are intentionally torch-free (the main `.venv` has no torch): they
monkeypatch backend imports/factories so no heavy ML dependency is ever loaded.
"""

from __future__ import annotations

import time

import numpy as np

import voice.stt as stt_module
from voice import STTUnavailable, VoiceAssistant, VoiceSettings
from voice.audio_io import trim_silence
from voice.stt import NexusWhisperSTT, _Backend


# ── helpers ──────────────────────────────────────────────────────────────────


def _stt_with(monkeypatch, factories, order):
    """Build a NexusWhisperSTT with injected backend factories/order."""
    monkeypatch.setattr(stt_module, "BACKEND_FACTORIES", factories)
    monkeypatch.setattr(NexusWhisperSTT, "BACKEND_ORDER", order)
    return NexusWhisperSTT(VoiceSettings(whisper_model="models/fake.bin"))


class FailingBackend(_Backend):
    name = "boom"

    def load(self):
        raise STTUnavailable("boom backend broken")

    def transcribe(self, audio, sample_rate):
        raise AssertionError("failing backend should never transcribe")


class WorkingBackend(_Backend):
    name = "good"

    def load(self):
        self.engine = object()
        return True

    def transcribe(self, audio, sample_rate):
        return "HELLO THERE"


class RuntimeFailingBackend(_Backend):
    name = "decoder"

    def load(self):
        self.engine = object()
        return True

    def transcribe(self, audio, sample_rate):
        raise STTUnavailable("decoder crashed")


class HangingBackend(_Backend):
    name = "hang"

    def load(self):
        self.engine = object()
        return True

    def transcribe(self, audio, sample_rate):
        time.sleep(30)
        return "LATE"


# ── STT backend failover ─────────────────────────────────────────────────────


def test_stt_failover_to_next_backend_on_configured_failure(monkeypatch):
    stt = _stt_with(
        monkeypatch,
        {"boom": FailingBackend, "good": WorkingBackend},
        ["boom", "good"],
    )
    audio = np.zeros(1600, dtype=np.float32)
    text = stt.transcribe(audio, 16000)
    assert text == "HELLO THERE"
    status = stt.get_status()
    assert status["status"] == "ok"
    assert status["active_backend"] == "good"
    # failing backend is tracked but did not sink the pipeline
    assert status["backends"]["boom"]["available"] is False
    assert status["backends"]["boom"]["error"]


def test_stt_all_backends_fail_raises_structured_unavailable(monkeypatch):
    stt = _stt_with(
        monkeypatch,
        {"boom": FailingBackend, "decoder": RuntimeFailingBackend},
        ["boom", "decoder"],
    )
    audio = np.zeros(1600, dtype=np.float32)
    try:
        stt.transcribe(audio, 16000)
        raise AssertionError("expected STTUnavailable")
    except STTUnavailable as exc:
        payload = exc.to_dict()
        assert payload["status"] == "unavailable"
        assert payload["backend"] is None
        assert len(payload["failures"]) == 2
        assert all(f["backend"] in ("boom", "decoder") for f in payload["failures"])
        assert "voice unavailable" in exc.reason.lower()
        assert "boom backend broken" in exc.reason
        assert "decoder crashed" in exc.reason


def test_stt_runtime_failure_fails_over_to_next_backend(monkeypatch):
    stt = _stt_with(
        monkeypatch,
        {"decoder": RuntimeFailingBackend, "good": WorkingBackend},
        ["decoder", "good"],
    )
    audio = np.zeros(1600, dtype=np.float32)
    assert stt.transcribe(audio, 16000) == "HELLO THERE"
    assert stt.get_status()["active_backend"] == "good"


# ── STT call timeout ─────────────────────────────────────────────────────────


def test_stt_call_timeout_does_not_freeze(monkeypatch):
    stt = _stt_with(monkeypatch, {"hang": HangingBackend}, ["hang"])
    audio = np.zeros(1600, dtype=np.float32)
    started = time.monotonic()
    try:
        stt.transcribe(audio, 16000, timeout=0.3)
        raise AssertionError("expected timeout")
    except STTUnavailable as exc:
        assert "timed out" in exc.reason
    assert time.monotonic() - started < 5.0


# ── VAD silence-trim ─────────────────────────────────────────────────────────


def test_trim_silence_trims_leading_and_trailing_silence():
    leading = np.zeros(4000, dtype=np.float32)
    speech = np.ones(800, dtype=np.float32) * 0.5
    trailing = np.zeros(4000, dtype=np.float32)
    signal = np.concatenate([leading, speech, trailing])

    trimmed = trim_silence(signal, 0.010, sample_rate=16000, hop_ms=10)
    assert trimmed.size > 0
    assert trimmed.size < signal.size
    assert trimmed.size >= speech.size
    # speech endpoints preserved, zeros removed
    assert trimmed[0] != 0.0
    assert trimmed[-1] != 0.0
    assert float(np.abs(trimmed).max()) == 0.5


def test_trim_silence_all_silence_returns_empty():
    all_silent = np.zeros(8000, dtype=np.float32)
    assert trim_silence(all_silent, 0.010, sample_rate=16000).size == 0


# ── pipeline lifecycle / state ───────────────────────────────────────────────


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeAudio:
    def __init__(self):
        self.opened = 0
        self.session = None
        self.stopped = 0

    def open_continuous_session(self, *args, **kwargs):
        self.opened += 1
        self.session = _FakeSession()
        return self.session

    def is_silent(self, audio, threshold):
        return False

    def stop_playback(self):
        self.stopped += 1


def _assistant_with_fake_audio():
    assistant = VoiceAssistant(VoiceSettings())
    fake = _FakeAudio()
    assistant.audio = fake
    return assistant, fake


def test_pipeline_state_guards_double_start():
    assistant, fake = _assistant_with_fake_audio()
    assert assistant.state == "idle"

    assistant.start_continuous_listening()
    assert assistant.state == "listening"
    assert fake.opened == 1

    # double-start must not open a second capture session
    assistant.start_continuous_listening()
    assert fake.opened == 1
    assert assistant.state == "listening"

    assistant.stop_continuous_listening()
    assert fake.session.closed is True
    assert assistant.state == "idle"


def test_pipeline_state_transitions_listening_processing():
    assistant, fake = _assistant_with_fake_audio()

    class _OkayStt:
        def transcribe(self, audio, sample_rate, timeout=None):
            assert assistant.state == "processing"
            return "HI"

    assistant.stt = _OkayStt()
    recorded = []

    class _RecAudio(fake.__class__):
        def record_until_pause(self, *args, **kwargs):
            recorded.append(assistant.state)
            return np.ones(1600, dtype=np.float32) * 0.5

        def is_silent(self, audio, threshold):
            return False

    assistant.audio = _RecAudio()
    text = assistant.listen_once()
    assert text == "HI"
    assert recorded == ["listening"]
    assert assistant.state == "idle"


# ── close() idempotent / ref-counted ─────────────────────────────────────────


def test_close_is_idempotent_and_refcounted():
    assistant, fake = _assistant_with_fake_audio()

    assistant.close()
    assert assistant._closed is True
    assert assistant.state == "stopped"
    calls = fake.stopped

    # second close is a no-op (idempotent)
    assistant.close()
    assert fake.stopped == calls

    # open()/close() are ref-counted and survive repeated opens
    assistant.open()
    assistant.open()
    assert assistant._refcount == 2
    assistant.close()
    assert assistant._closed is False  # still referenced
    assistant.close()
    assert assistant._closed is True   # fully released now
    assert assistant._refcount == 0
    assert assistant.state == "stopped"

    # reopening after full close works
    assistant.open()
    assert assistant._closed is False
    assert assistant.state == "idle"
