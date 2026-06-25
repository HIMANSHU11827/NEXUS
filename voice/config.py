from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VoiceSettings:
    enabled: bool = False
    auto_speak: bool = True
    microphone_device: Optional[int | str] = None
    speaker_device: Optional[int | str] = None
    sample_rate: int = 16000
    record_seconds: float = 6.0
    silence_threshold: float = 0.010
    min_speech_seconds: float = 0.18
    silence_timeout_seconds: float = 0.9
    whisper_model: str = "models/local/voice/ggml-tiny-q5_1.bin"
    whisper_device: str = "auto"
    whisper_language: str = "auto"
    whisper_chunk_length_s: int = 15
    whisper_batch_size: int = 1
    kitten_model: str = "KittenML/kitten-tts-nano-0.8-int8"
    voice_name: str = "Jasper"
    speech_speed: float = 1.0
    volume: float = 1.0
    push_to_talk_key: str = "none"
    continuous_listening: bool = True
    wake_word_enabled: bool = False
    wake_word: str = "nexus"
    allow_text_fallback: bool = True
    keep_models_loaded: bool = True
    assistant_timeout_seconds: float = 45.0
    require_wake_word: bool = False

    @classmethod
    def from_config(cls, config: Any = None) -> "VoiceSettings":
        """Load voice settings from ProfilesManager or a config object.

        If config is None, uses the active ProfilesManager singleton.
        Falls back to NEXUS_PROVIDER_TIMEOUT env var for timeout.
        """
        if config is None:
            from config.config_loader import NexusConfigLoader
            try:
                pm = NexusConfigLoader()
                raw = pm.get("voice", {})
            except Exception:
                raw = {}
        elif hasattr(config, "get"):
            raw = config.get("voice", {})
        else:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        data: Dict[str, Any] = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in raw:
                data[field_name] = raw[field_name]
        if "assistant_timeout_seconds" not in data or data["assistant_timeout_seconds"] == cls.assistant_timeout_seconds:
            env_timeout = os.getenv("NEXUS_PROVIDER_TIMEOUT")
            if env_timeout:
                try:
                    data["assistant_timeout_seconds"] = float(env_timeout)
                except ValueError:
                    pass
        return cls(**data)
