from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VoiceSettings:
    enabled: bool = False
    auto_speak: bool = True
    microphone_device: Optional[int | str] = None
    speaker_device: Optional[int | str] = None
    sample_rate: int = 16000
    record_seconds: float = 5.0
    silence_threshold: float = 0.01
    min_speech_seconds: float = 0.25
    silence_timeout_seconds: float = 0.8
    whisper_model: str = "models/local/voice/distil-whisper-large-v3"
    whisper_device: str = "auto"
    whisper_language: str = "auto"
    whisper_chunk_length_s: int = 15
    whisper_batch_size: int = 1
    kitten_model: str = "KittenML/kitten-tts-micro-0.8"
    voice_name: str = "Jasper"
    speech_speed: float = 1.0
    volume: float = 1.0
    push_to_talk_key: str = "enter"
    wake_word_enabled: bool = False
    wake_word: str = "nexus"
    allow_text_fallback: bool = True
    keep_models_loaded: bool = True
    assistant_timeout_seconds: float = 45.0
    require_wake_word: bool = False

    @classmethod
    def from_config(cls, config: Any) -> "VoiceSettings":
        raw = config.get("voice", {}) if hasattr(config, "get") else {}
        if not isinstance(raw, dict):
            raw = {}
        data: Dict[str, Any] = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in raw:
                data[field_name] = raw[field_name]
        if "assistant_timeout_seconds" not in data:
            env_timeout = os.getenv("NEXUS_PROVIDER_TIMEOUT")
            if env_timeout:
                try:
                    data["assistant_timeout_seconds"] = float(env_timeout)
                except ValueError:
                    pass
        return cls(**data)
