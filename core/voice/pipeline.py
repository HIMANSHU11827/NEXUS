from __future__ import annotations

import concurrent.futures
import re
from typing import Optional

from core.voice.audio_io import AudioIO, AudioUnavailable
from core.voice.config import VoiceSettings
from core.voice.stt import NexusWhisperSTT
from core.voice.tts import KittenTTSSpeaker


class VoiceAssistant:
    def __init__(self, settings: Optional[VoiceSettings] = None, loop=None):
        if settings is None:
            from core.config_loader import NexusConfigLoader
            settings = VoiceSettings.from_config(NexusConfigLoader())
        self.settings = settings
        self.audio = AudioIO(settings.microphone_device, settings.speaker_device, settings.sample_rate, settings.volume)
        self.stt = NexusWhisperSTT(settings)
        self.tts = KittenTTSSpeaker(settings, self.audio)
        self.loop = loop

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

    def listen_once(self, status_callback: Optional[callable] = None) -> str:
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
            return quick_reply
        if self.loop is None:
            from orchestrators.loop import NexusLoop
            self.loop = NexusLoop()
        
        # Optimize voice mode: shorter timeout and voice_mode flag
        timeout = 25.0 # Shorter for voice
        voice_prompt = (
            f"{text}\n\n"
            "[VOICE_MODE]: Keep it extremely brief (max 15 words). Conversational. No markdown."
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.loop.run, voice_prompt, voice_mode=True)
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
        return self._clean_assistant_reply(response)

    def speak(self, text: str, blocking: bool = True) -> bool:
        if not self.settings.auto_speak:
            return False
        try:
            self.tts.speak(text, blocking=blocking)
            return True
        except Exception:
            return False

    def stop_speaking(self) -> None:
        self.tts.stop()

    def voice_turn(
        self,
        fallback_text: Optional[str] = None,
        *,
        prompt_text_fallback: bool = True,
        speech_blocking: bool = False,
        status_callback: Optional[callable] = None,
    ) -> tuple[str, str, bool]:
        try:
            user_text = self.listen_once(status_callback=status_callback)
        except (AudioUnavailable, RuntimeError):
            if not self.settings.allow_text_fallback or not prompt_text_fallback:
                raise
            user_text = fallback_text or input("Text fallback> ").strip()
        if not user_text and self.settings.allow_text_fallback and prompt_text_fallback:
            user_text = fallback_text or input("Text fallback> ").strip()
        if not user_text:
            return "", "", False
        print(f"You: {user_text}")
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
        if status_callback:
            status_callback("processing")
        else:
            print("[voice] thinking...")
        
        reply = self.ask_text(user_text)
        
        if reply and not status_callback:
            print("[voice] speaking...")
        
        spoken = self.speak(reply, blocking=speech_blocking)
        return user_text, reply, spoken

    @staticmethod
    def _clean_assistant_reply(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\[NEXUS_BOOT\]:[^\n]*", "", text)
        text = re.sub(r"\[THINKING:[^\]]+\]", "", text)
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
        if len(cleaned.split()) >= 8 and not any(
            word in cleaned
            for word in (
                "nexus",
                "hello",
                "hi",
                "open",
                "run",
                "fix",
                "explain",
                "summarize",
                "what",
                "why",
                "how",
                "please",
            )
        ):
            return True
        return False

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
