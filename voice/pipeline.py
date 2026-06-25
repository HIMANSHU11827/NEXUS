from __future__ import annotations

import concurrent.futures
import re
import sys
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from voice.audio_io import AudioIO, AudioUnavailable
from voice.config import VoiceSettings
from voice.stt import NexusWhisperSTT
from voice.tts import KittenTTSSpeaker


def _safe_console_text(value: str) -> str:
    text = str(value or "")
    try:
        return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        return text


class VoiceAssistant:
    def __init__(self, settings: Optional[VoiceSettings] = None, loop=None, session_id: str = "default"):
        if settings is None:
            from config.config_loader import NexusConfigLoader
            settings = VoiceSettings.from_config(NexusConfigLoader())
        self.settings = settings
        self.session_id = session_id
        self.audio = AudioIO(settings.microphone_device, settings.speaker_device, settings.sample_rate, settings.volume)
        self.stt = NexusWhisperSTT(settings)
        self.tts = KittenTTSSpeaker(settings, self.audio)
        self.loop = loop
        self._continuous_session = None
        self._continuous_status_callback = None

    def _ensure_loop(self):
        if self.loop is None:
            from orchestrators.loop import NexusLoop
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
        if self._continuous_session is not None and self._continuous_status_callback is status_callback:
            return
        self.stop_continuous_listening()
        self._continuous_status_callback = status_callback
        self._continuous_session = self.audio.open_continuous_session(
            self.settings.record_seconds,
            self.settings.silence_threshold,
            self.settings.silence_timeout_seconds,
            self.settings.min_speech_seconds,
            status_callback=status_callback,
        )

    def stop_continuous_listening(self) -> None:
        if self._continuous_session is not None:
            self._continuous_session.close()
        self._continuous_session = None
        self._continuous_status_callback = None

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
        if self.audio.is_silent(audio, self.settings.silence_threshold):
            return ""
        # Transcription status silenced
        if status_callback:
            status_callback("processing")
        text = self.stt.transcribe(audio, self.settings.sample_rate)
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
                pass
        if not status_callback:
            print("[voice] thinking...")
        
        reply = self.ask_text(user_text)
        if before_speak_callback is not None:
            try:
                before_speak_callback(user_text, reply)
            except Exception:
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
