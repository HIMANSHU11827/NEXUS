from __future__ import annotations

import concurrent.futures
import logging
import re
import sys
from typing import Optional

logger = logging.getLogger("nexus.voice.pipeline")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning("voice/pipeline.py:12 : suppressed error", exc_info=True)
        pass

from voice.audio_io import AudioIO, AudioUnavailable
from voice.config import VoiceSettings
from voice.stt import NexusWhisperSTT, STTUnavailable
from voice.tts import KittenTTSSpeaker


def _safe_console_text(value: str) -> str:
    text = str(value or "")
    try:
        return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        return text


# Lifecycle states exposed via VoiceAssistant.state
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_PROCESSING = "processing"
STATE_STOPPED = "stopped"


class VoiceAssistant:
    @classmethod
    def from_config(cls, config_loader=None, loop=None, session_id: str = "default"):
        """Create a VoiceAssistant instance from configure loader."""
        if config_loader is None:
            from configure.config_loader import NexusConfigLoader
            config_loader = NexusConfigLoader()
        settings = VoiceSettings.from_config(config_loader)
        return cls(settings, loop=loop, session_id=session_id)

    def __init__(self, settings: Optional[VoiceSettings] = None, loop=None, session_id: str = "default"):
        if settings is None:
            from configure.config_loader import NexusConfigLoader
            settings = VoiceSettings.from_config(NexusConfigLoader())
        self.settings = settings
        self.session_id = session_id
        # Lifecycle state + ref-counted resource ownership.
        self._state = STATE_IDLE
        self._refcount = 0
        self._closed = False
        self.audio = AudioIO(
            settings.microphone_device,
            settings.speaker_device,
            settings.sample_rate,
            settings.volume,
            vad_enabled=bool(getattr(settings, "vad_enabled", True)),
        )
        self.stt = NexusWhisperSTT(settings)
        self.tts = KittenTTSSpeaker(settings, self.audio)
        self.loop = loop
        self._continuous_session = None
        self._continuous_status_callback = None
        # New: Voice history and statistics
        self._transcription_history: list[dict] = []
        self._voice_statistics: dict = {
            "total_transcriptions": 0,
            "total_speak_time": 0.0,
            "successful_turns": 0,
            "failed_turns": 0,
            "wake_word_activations": 0,
            "session_start_time": None,
        }

    @property
    def state(self) -> str:
        """Current pipeline lifecycle state.

        One of ``idle``/``listening``/``processing``/``stopped``.
        """
        return self._state

    def open(self) -> "VoiceAssistant":
        """Open the pipeline, surviving a previous ``close()``.

        Ref-counted: resources are only released once every matching ``close()``
        has been called.
        """
        if self._closed:
            self._closed = False
            self._refcount = 0
            self._state = STATE_IDLE
        self._refcount += 1
        return self

    def close(self) -> None:
        """Release pipeline resources. Idempotent and ref-counted."""
        if self._closed:
            return
        self._refcount = max(0, self._refcount - 1)
        if self._refcount > 0:
            return
        self._hard_close()

    def _hard_close(self) -> None:
        try:
            self.stop_continuous_listening()
        except Exception:
            logger.warning("voice/pipeline.py:close stop_continuous_listening: suppressed error", exc_info=True)
            pass
        try:
            self.stop_speaking()
        except Exception:
            logger.warning("voice/pipeline.py:close stop_speaking: suppressed error", exc_info=True)
            pass
        try:
            self.audio.stop_playback()
        except Exception:
            logger.warning("voice/pipeline.py:close audio stop_playback: suppressed error", exc_info=True)
            pass
        self._closed = True
        self._state = STATE_STOPPED

    def __enter__(self) -> "VoiceAssistant":
        return self.open()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _ensure_loop(self):
        if self.loop is None:
            from orchestrators import NexusLoop
            self.loop = NexusLoop()
            self.loop.load_memory(self.session_id)
        return self.loop

    def _persist_voice_turn(self, user_text: str, reply_text: str) -> None:
        loop = self._ensure_loop()
        loop.sync_memory()
        loop.memory.append({"role": "user", "content": str(user_text or "")})
        loop.memory.append({"role": "assistant", "content": str(reply_text or "")})
        loop.save_memory()

    def warmup(self) -> None:
        if self.settings.keep_models_loaded:
            try:
                self.stt.load()
            except Exception as e:
                print(f"[voice-warning] Failed to warmup STT: {e}")
            try:
                self.tts.load()
            except Exception as e:
                print(f"[voice-warning] Failed to warmup TTS: {e}")

    def start_continuous_listening(self, status_callback: Optional[callable] = None) -> None:
        if self._continuous_session is not None:
            # Guard double-start: never open a second capture session.
            if status_callback is not None:
                self._continuous_status_callback = status_callback
            self._state = STATE_LISTENING
            return
        session = self.audio.open_continuous_session(
            self.settings.record_seconds,
            self.settings.silence_threshold,
            self.settings.silence_timeout_seconds,
            self.settings.min_speech_seconds,
            status_callback=status_callback,
        )
        self._continuous_session = session
        self._continuous_status_callback = status_callback
        self._state = STATE_LISTENING

    def stop_continuous_listening(self) -> None:
        if self._continuous_session is not None:
            try:
                self._continuous_session.close()
            except Exception:
                logger.warning("voice/pipeline.py:stop_continuous_listening: suppressed error", exc_info=True)
                pass
        self._continuous_session = None
        self._continuous_status_callback = None
        if self._state not in (STATE_STOPPED, STATE_PROCESSING):
            self._state = STATE_IDLE

    def set_continuous_listening_paused(self, paused: bool) -> None:
        if self._continuous_session is None:
            return
        if paused:
            self._continuous_session.pause_capture()
        else:
            self._continuous_session.resume_capture()

    def listen_once(
        self,
        status_callback: Optional[callable] = None,
        *,
        continuous: bool = False,
        timeout: Optional[float] = None,
    ) -> str:
        if not continuous:
            self._state = STATE_LISTENING
        try:
            if continuous:
                self.start_continuous_listening(status_callback=status_callback)
                audio = self._continuous_session.read_utterance(timeout=timeout)
            else:
                audio = self.audio.record_until_pause(
                    self.settings.record_seconds,
                    self.settings.silence_threshold,
                    self.settings.silence_timeout_seconds,
                    self.settings.min_speech_seconds,
                    status_callback=status_callback,
                )
        except Exception:
            if not continuous:
                self._state = STATE_IDLE
            raise
        if self.audio.is_silent(audio, self.settings.silence_threshold):
            if not continuous:
                self._state = STATE_IDLE
            return ""
        # Transcription status silenced
        if status_callback:
            status_callback("processing")
        self._state = STATE_PROCESSING
        stt_timeout = float(getattr(self.settings, "stt_timeout_seconds", 30.0))
        try:
            text = self.stt.transcribe(audio, self.settings.sample_rate, timeout=stt_timeout)
        except STTUnavailable as exc:
            # Preserve structured reason as a plain RuntimeError so downstream
            # text-fallback handles it; never let one backend freeze the caller.
            raise RuntimeError(exc.reason) from exc
        finally:
            if continuous and self._continuous_session is not None:
                self._state = STATE_LISTENING
            else:
                self._state = STATE_IDLE
        if self._looks_like_corrupt_transcript(text):
            print("[voice] transcript looked corrupted. ignoring and listening again.")
            return ""
        if self._looks_like_stt_hallucination(text):
            print("[voice] likely background/noise transcript. ignoring and listening again.")
            return ""
        return text

    def ask_text(self, text: str) -> str:
        quick_reply = self._quick_voice_reply(text)
        if quick_reply is not None:
            self._persist_voice_turn(text, quick_reply)
            return quick_reply
        self._ensure_loop()
        
        # Keep voice turns responsive while respecting config overrides.
        timeout = max(8.0, float(self.settings.assistant_timeout_seconds))
        import asyncio
        def _run_coroutine():
            return asyncio.run(self.loop.run(text, voice_mode=True))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_coroutine)
            try:
                response = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as exc:
                try:
                    self.loop.abort()
                except Exception:
                    logger.warning("voice/pipeline.py:147 _run_coroutine: suppressed error", exc_info=True)
                    pass
                raise TimeoutError(
                    f"NEXUS took longer than {timeout:.0f}s to answer. "
                    "Try a shorter prompt or check the local model."
                ) from exc
        cleaned = self._clean_assistant_reply(response)
        if self._looks_like_backend_failure(cleaned):
            cleaned = self._friendly_backend_failure(cleaned)
            try:
                if getattr(self.loop, "memory", None):
                    self.loop.memory[-1]["content"] = cleaned
                    self.loop.save_memory()
            except Exception:
                logger.warning("voice/pipeline.py:160 : suppressed error", exc_info=True)
                pass
        return cleaned

    def speak(self, text: str, blocking: bool = True) -> bool:
        if not self.settings.auto_speak:
            return False
        paused_continuous = self._continuous_session is not None
        if paused_continuous:
            self.set_continuous_listening_paused(True)
        try:
            self.tts.speak(text, blocking=blocking)
            return True
        except Exception:
            return False
        finally:
            if paused_continuous:
                self.set_continuous_listening_paused(False)

    def stop_speaking(self) -> None:
        self.tts.stop()

    def voice_turn(
        self,
        fallback_text: Optional[str] = None,
        *,
        prompt_text_fallback: bool = True,
        speech_blocking: bool = False,
        status_callback: Optional[callable] = None,
        continuous: bool = False,
        on_transcript_callback: Optional[callable] = None,
        before_speak_callback: Optional[callable] = None,
    ) -> tuple[str, str, bool]:
        try:
            user_text = self.listen_once(
                status_callback=status_callback,
                continuous=continuous,
                timeout=0.25 if continuous else None,
            )
        except (AudioUnavailable, RuntimeError):
            if not self.settings.allow_text_fallback or not prompt_text_fallback:
                raise
            user_text = fallback_text or input("Text fallback> ").strip()
        if not user_text and self.settings.allow_text_fallback and prompt_text_fallback:
            user_text = fallback_text or input("Text fallback> ").strip()
        if not user_text:
            return "", "", False
        if self.settings.require_wake_word:
            wake = self.settings.wake_word.lower().strip()
            if wake and wake not in user_text.lower():
                print(f"[voice] wake word '{wake}' not heard. ignoring.")
                return user_text, "", False
        if self.settings.wake_word_enabled:
            wake = self.settings.wake_word.lower().strip()
            if wake and wake not in user_text.lower():
                return user_text, "", False
            user_text = re.sub(re.escape(wake), "", user_text, flags=re.IGNORECASE).strip(" ,.")
        if on_transcript_callback is not None:
            try:
                on_transcript_callback(user_text)
            except Exception:
                logger.warning("voice/pipeline.py:220 : suppressed error", exc_info=True)
                pass
        if not status_callback:
            print("[voice] thinking...")
        
        reply = self.ask_text(user_text)
        if before_speak_callback is not None:
            try:
                before_speak_callback(user_text, reply)
            except Exception:
                logger.warning("voice/pipeline.py:229 : suppressed error", exc_info=True)
                pass
        
        if reply:
            if status_callback:
                status_callback("speaking")
            else:
                print("[voice] speaking...")
        
        spoken = self.speak(reply, blocking=speech_blocking)
        return user_text, reply, spoken

    @staticmethod
    def _clean_assistant_reply(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\[NEXUS_BOOT\]:[^\n]*", "", text)
        text = re.sub(r"\[THINKING:[^\]]+\]", "", text)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"</?thinking>", "", text, flags=re.IGNORECASE)
        text = text.replace("TASK_COMPLETE", "")
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _looks_like_corrupt_transcript(text: str) -> bool:
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        compact = re.sub(r"\s+", "", cleaned)
        if len(compact) < 6:
            return False
        chars = [c for c in compact if c.isalnum()]
        if not chars:
            return False
        unique_ratio = len(set(chars)) / max(1, len(chars))
        digit_ratio = sum(ch.isdigit() for ch in chars) / max(1, len(chars))
        repeated_token = re.fullmatch(r"([A-Za-z0-9])(?:[-_\s]?\1){5,}", cleaned)
        if repeated_token:
            return True
        if digit_ratio > 0.6 and unique_ratio < 0.2:
            return True
        if len(cleaned) > 20 and unique_ratio < 0.12:
            return True
        return False

    @staticmethod
    def _looks_like_stt_hallucination(text: str) -> bool:
        cleaned = re.sub(r"[^\w\s']", "", (text or "").lower()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return False
        stock_phrases = {
            "thank you for watching",
            "thanks for watching",
            "see you next time",
            "please subscribe",
            "like and subscribe",
        }
        if cleaned in stock_phrases:
            return True
        return False

    @staticmethod
    def _looks_like_backend_failure(text: str) -> bool:
        cleaned = (text or "").strip().lower()
        if not cleaned:
            return False
        failure_signals = (
            "error:",
            "error in ",
            "[provider_error]",
            "failed to reach",
            "max retries exceeded",
            "name resolution error",
            "getaddrinfo failed",
            "connectionpool(",
            "api returned ",
            "provider has no valid credentials",
            "no responsive brain found",
        )
        return any(signal in cleaned for signal in failure_signals)

    @staticmethod
    def _friendly_backend_failure(text: str) -> str:
        cleaned = (text or "").lower()
        if "api_key" in cleaned or "credentials" in cleaned:
            return "I could not use the selected voice model because its API key or credentials are missing."
        if "name resolution" in cleaned or "getaddrinfo failed" in cleaned or "max retries exceeded" in cleaned:
            return "I could not reach the voice model service. Please check your internet connection or switch to a local provider."
        return "I could not reach the selected voice model just now. Please try again or switch to a working local provider."

    @staticmethod
    def _quick_voice_reply(text: str) -> Optional[str]:
        cleaned = re.sub(r"[^\w\s]", "", (text or "").lower()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        greetings = {
            "hello": "Hello. I am listening.",
            "hi": "Hi. I am listening.",
            "hey": "Hey. I am listening.",
            "you": "I am here. Please tell me what you need.",
        }
        return greetings.get(cleaned)

    # New: Enhanced voice features
    def voice_status(self) -> dict:
        """Return structured pipeline + STT backend health for diagnostics."""
        return {
            "status": "ok" if self._state != STATE_STOPPED else "stopped",
            "state": self._state,
            "listening": self._continuous_session is not None,
            "tts_loaded": self.tts._model is not None,
            "stt": self.stt.get_status(),
        }

    def get_voice_statistics(self) -> dict:
        """Return comprehensive voice usage statistics."""
        import time
        stats = self._voice_statistics.copy()
        if stats["session_start_time"] is None:
            stats["session_duration"] = 0.0
        else:
            stats["session_duration"] = time.time() - stats["session_start_time"]
        stats["transcription_history_size"] = len(self._transcription_history)
        stats["settings"] = {
            "enabled": self.settings.enabled,
            "auto_speak": self.settings.auto_speak,
            "continuous_listening": self.settings.continuous_listening,
            "voice_name": self.settings.voice_name,
            "whisper_language": self.settings.whisper_language,
        }
        return stats

    def get_transcription_history(self, limit: Optional[int] = None) -> list[dict]:
        """Return transcription history, optionally limited."""
        if limit is None:
            return self._transcription_history.copy()
        return self._transcription_history[-limit:]

    def clear_transcription_history(self) -> None:
        """Clear transcription history."""
        self._transcription_history.clear()

    def add_transcription_to_history(self, transcript: str, reply: str, success: bool = True) -> None:
        """Add a transcription to history with metadata."""
        import time
        entry = {
            "timestamp": time.time(),
            "transcript": transcript,
            "reply": reply,
            "success": success,
            "voice_name": self.settings.voice_name,
            "language": self.settings.whisper_language,
        }
        self._transcription_history.append(entry)
        
        # Trim history if needed
        limit = self.settings.transcription_history_limit
        if len(self._transcription_history) > limit:
            self._transcription_history = self._transcription_history[-limit:]
        
        # Update statistics
        self._voice_statistics["total_transcriptions"] += 1
        if success:
            self._voice_statistics["successful_turns"] += 1
        else:
            self._voice_statistics["failed_turns"] += 1

    def search_transcriptions(self, query: str) -> list[dict]:
        """Search transcription history for a query."""
        query_lower = query.lower()
        results = []
        for entry in self._transcription_history:
            if query_lower in entry["transcript"].lower() or query_lower in entry["reply"].lower():
                results.append(entry)
        return results

    def export_voice_data(self, format: str = "json") -> str:
        """Export voice data in JSON or text format."""
        import time
        export_data = {
            "statistics": self.get_voice_statistics(),
            "transcription_history": self._transcription_history,
            "settings": {
                "enabled": self.settings.enabled,
                "auto_speak": self.settings.auto_speak,
                "voice_name": self.settings.voice_name,
                "speech_speed": self.settings.speech_speed,
                "volume": self.settings.volume,
                "continuous_listening": self.settings.continuous_listening,
            },
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        if format == "json":
            import json
            return json.dumps(export_data, indent=2)
        elif format == "text":
            lines = [
                f"NEXUS Voice Data Export - {self.session_id}",
                f"Exported: {export_data['exported_at']}",
                "",
                "=== Statistics ===",
                f"Total transcriptions: {export_data['statistics']['total_transcriptions']}",
                f"Successful turns: {export_data['statistics']['successful_turns']}",
                f"Failed turns: {export_data['statistics']['failed_turns']}",
                f"Session duration: {export_data['statistics']['session_duration']:.1f}s",
                "",
                "=== Recent Transcriptions ===",
            ]
            for entry in self._transcription_history[-10:]:
                lines.append(f"[{entry['timestamp']}] {entry['transcript'][:100]}")
                lines.append(f"Reply: {entry['reply'][:100]}")
                lines.append("")
            return "\n".join(lines)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def get_available_voices(self) -> list[str]:
        """Return list of available KittenTTS voices."""
        return ["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"]

    def get_available_languages(self) -> list[str]:
        """Return list of supported Whisper languages."""
        return ["auto", "en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko", "hi", "ar"]

    def test_audio_devices(self) -> dict:
        """Test and return available audio devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            return {
                "input_devices": [d for d in devices if d['max_input_channels'] > 0],
                "output_devices": [d for d in devices if d['max_output_channels'] > 0],
                "default_input": sd.default.device[0],
                "default_output": sd.default.device[1],
            }
        except Exception as e:
            return {"error": str(e), "input_devices": [], "output_devices": []}

    def reset_statistics(self) -> None:
        """Reset voice statistics."""
        self._voice_statistics = {
            "total_transcriptions": 0,
            "total_speak_time": 0.0,
            "successful_turns": 0,
            "failed_turns": 0,
            "wake_word_activations": 0,
            "session_start_time": None,
        }
