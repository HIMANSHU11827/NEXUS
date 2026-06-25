from __future__ import annotations

import os
import queue
import sys
import threading
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import re
from typing import List
from contextlib import contextmanager, redirect_stdout

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from voice.audio_io import AudioIO
from voice.config import VoiceSettings


def speech_text(text: str) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace(" — ", ". ")
    cleaned = cleaned.replace(" - ", ". ")
    return re.sub(r"\s+", " ", cleaned).strip()


def sentence_chunks(text: str, max_chars: int = 160) -> List[str]:
    cleaned = speech_text(text)
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > max_chars:
            words = piece.split()
            for word in words:
                candidate = f"{current} {word}".strip()
                if len(candidate) > max_chars and current:
                    chunks.append(current)
                    current = word
                else:
                    current = candidate
            continue
        candidate = f"{current} {piece}".strip()
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def low_latency_chunks(text: str, max_chars: int = 72) -> List[str]:
    cleaned = speech_text(text)
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?,:;])\s+", cleaned)
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        words = piece.split()
        if not words:
            continue
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars and current:
                chunks.append(current)
                current = word
            else:
                current = candidate
        if current and current[-1:] in ".!?":
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


class KittenTTSSpeaker:
    sample_rate = 24000

    def __init__(self, settings: VoiceSettings, audio_io: AudioIO):
        self.settings = settings
        self.audio_io = audio_io
        self._model = None
        self._lock = threading.Lock()
        self._speaking_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from kittentts import KittenTTS
            except ImportError as exc:
                raise RuntimeError(
                    "KittenTTS is not installed. Install: "
                    "python -m pip install https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl"
                ) from exc
            print(f"[voice] Initializing KittenTTS Engine ({self.settings.kitten_model})...")
            try:
                # Try loading with ONNX if specified or detected
                if "onnx" in str(self.settings.kitten_model).lower():
                    self._model = KittenTTS(self.settings.kitten_model, use_onnx=True)
                else:
                    self._model = KittenTTS(self.settings.kitten_model)
            except Exception as e:
                print(f"[voice-warning] Primary load failed, trying fallback: {e}")
                self._model = KittenTTS(self.settings.kitten_model)
            # print("[voice] KittenTTS Engine Online.")

    @contextmanager
    def _suppress_stdout(self):
        with open(os.devnull, 'w') as fnull:
            with redirect_stdout(fnull):
                yield

    def synthesize(self, text: str):
        self.load()
        with self._suppress_stdout():
            return self._model.generate(
                text,
                voice=self.settings.voice_name,
                speed=float(self.settings.speech_speed),
            )

    def stop(self) -> None:
        self._stream_stop.set()
        self.audio_io.stop_playback()

    def speak(self, text: str, blocking: bool = True) -> None:
        self.stop()
        self._stream_stop = threading.Event()
        if blocking:
            self._speak_worker(text)
            return
        thread = threading.Thread(target=self._speak_worker, args=(text,), daemon=True)
        self._speaking_thread = thread
        thread.start()

    def _speak_worker(self, text: str) -> None:
        chunks = low_latency_chunks(text)
        if not chunks:
            return
        try:
            audio_queue: "queue.Queue[tuple[str, object] | None]" = queue.Queue(maxsize=3)

            def producer():
                try:
                    for chunk in chunks:
                        if self._stream_stop.is_set():
                            break
                        audio = self.synthesize(chunk)
                        audio_queue.put((chunk, audio))
                    audio_queue.put(None)
                except Exception as exc:
                    audio_queue.put(("__error__", exc))

            producer_thread = threading.Thread(target=producer, daemon=True)
            producer_thread.start()

            while not self._stream_stop.is_set():
                item = audio_queue.get()
                if item is None:
                    break
                label, payload = item
                if label == "__error__":
                    raise payload
                self.audio_io.play(payload, self.sample_rate)
                if self._stream_stop.is_set():
                    break
                time.sleep(0.04)
        except Exception as e:
            print(f"[voice-error] TTS synthesis/playback failed: {e}")
