"""
NEXUS Settings Schema — Typed configuration models.

All values have defaults matching the base profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SystemSettings:
    """System-level NEXUS settings."""

    kernel_mode: str = "recursive_frontier"
    default_provider: str = "local"
    provider_name: str = "SOVEREIGN_BRAIN"
    brain_mode: str = "AUTO"
    shell: str = "ghost_v1"
    branding: str = "🦀"
    workspace_root: str = "./workspace"
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SystemSettings":
        if not data:
            return cls()
        return cls(
            kernel_mode=data.get("kernel_mode", cls.kernel_mode),
            default_provider=data.get("default_provider", cls.default_provider),
            provider_name=data.get("provider_name", cls.provider_name),
            brain_mode=data.get("brain_mode", cls.brain_mode),
            shell=data.get("shell", cls.shell),
            branding=data.get("branding", cls.branding),
            workspace_root=data.get("workspace_root", cls.workspace_root),
            log_level=data.get("log_level", cls.log_level),
        )


@dataclass
class SecuritySettings:
    """Security and safety settings."""

    safety_strictness: float = 0.8
    prover_gate_active: bool = False
    sandbox_mode: str = "firecracker_ev"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SecuritySettings":
        if not data:
            return cls()
        return cls(
            safety_strictness=float(data.get("safety_strictness", cls.safety_strictness)),
            prover_gate_active=bool(data.get("prover_gate_active", cls.prover_gate_active)),
            sandbox_mode=str(data.get("sandbox_mode", cls.sandbox_mode)),
        )


@dataclass
class MemorySettings:
    """Memory persistence settings."""

    persistence: str = "atomic_checkpoints"
    vault_mode: str = "gravity_rag"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "MemorySettings":
        if not data:
            return cls()
        return cls(
            persistence=data.get("persistence", cls.persistence),
            vault_mode=data.get("vault_mode", cls.vault_mode),
        )


@dataclass
class VoiceSettings:
    """Voice/audio settings."""

    enabled: bool = False
    auto_speak: bool = True
    microphone_device: Any = None
    speaker_device: Any = None
    sample_rate: int = 16000
    record_seconds: float = 60.0
    silence_threshold: float = 0.008
    min_speech_seconds: float = 0.25
    silence_timeout_seconds: float = 2.0
    whisper_model: str = "models/local/voice/distil-whisper-large-v3"
    whisper_device: str = "auto"
    whisper_language: str = "auto"
    whisper_chunk_length_s: int = 15
    whisper_batch_size: int = 1
    kitten_model: str = "KittenML/kitten-tts-micro-0.8"
    voice_name: str = "Jasper"
    speech_speed: float = 1.2
    volume: float = 1.0
    push_to_talk_key: str = "none"
    wake_word_enabled: bool = False
    wake_word: str = "nexus"
    allow_text_fallback: bool = True
    keep_models_loaded: bool = True
    assistant_timeout_seconds: float = 45.0
    require_wake_word: bool = False

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "VoiceSettings":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            auto_speak=bool(data.get("auto_speak", cls.auto_speak)),
            microphone_device=data.get("microphone_device", cls.microphone_device),
            speaker_device=data.get("speaker_device", cls.speaker_device),
            sample_rate=int(data.get("sample_rate", cls.sample_rate)),
            record_seconds=float(data.get("record_seconds", cls.record_seconds)),
            silence_threshold=float(data.get("silence_threshold", cls.silence_threshold)),
            min_speech_seconds=float(data.get("min_speech_seconds", cls.min_speech_seconds)),
            silence_timeout_seconds=float(data.get("silence_timeout_seconds", cls.silence_timeout_seconds)),
            whisper_model=str(data.get("whisper_model", cls.whisper_model)),
            whisper_device=str(data.get("whisper_device", cls.whisper_device)),
            whisper_language=str(data.get("whisper_language", cls.whisper_language)),
            whisper_chunk_length_s=int(data.get("whisper_chunk_length_s", cls.whisper_chunk_length_s)),
            whisper_batch_size=int(data.get("whisper_batch_size", cls.whisper_batch_size)),
            kitten_model=str(data.get("kitten_model", cls.kitten_model)),
            voice_name=str(data.get("voice_name", cls.voice_name)),
            speech_speed=float(data.get("speech_speed", cls.speech_speed)),
            volume=float(data.get("volume", cls.volume)),
            push_to_talk_key=str(data.get("push_to_talk_key", cls.push_to_talk_key)),
            wake_word_enabled=bool(data.get("wake_word_enabled", cls.wake_word_enabled)),
            wake_word=str(data.get("wake_word", cls.wake_word)),
            allow_text_fallback=bool(data.get("allow_text_fallback", cls.allow_text_fallback)),
            keep_models_loaded=bool(data.get("keep_models_loaded", cls.keep_models_loaded)),
            assistant_timeout_seconds=float(data.get("assistant_timeout_seconds", cls.assistant_timeout_seconds)),
            require_wake_word=bool(data.get("require_wake_word", cls.require_wake_word)),
        )


@dataclass
class ProfileConfig:
    """Complete resolved configuration for a single profile."""

    system: SystemSettings = field(default_factory=SystemSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    providers: dict = field(default_factory=lambda: {"cloud": {}, "local": {}})
    custom_tool_configs: dict = field(default_factory=dict)
    custom_skill_configs: dict = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)
    disabled_skills: list = field(default_factory=list)
    disabled_tools: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Export full config as nested dict (for backward compatibility)."""
        return {
            "system": {
                "kernel_mode": self.system.kernel_mode,
                "default_provider": self.system.default_provider,
                "provider_name": self.system.provider_name,
                "brain_mode": self.system.brain_mode,
                "shell": self.system.shell,
                "branding": self.system.branding,
                "workspace_root": self.system.workspace_root,
                "log_level": self.system.log_level,
            },
            "security": {
                "safety_strictness": self.security.safety_strictness,
                "prover_gate_active": self.security.prover_gate_active,
                "sandbox_mode": self.security.sandbox_mode,
            },
            "memory": {
                "persistence": self.memory.persistence,
                "vault_mode": self.memory.vault_mode,
            },
            "voice": {
                "enabled": self.voice.enabled,
                "auto_speak": self.voice.auto_speak,
                "microphone_device": self.voice.microphone_device,
                "speaker_device": self.voice.speaker_device,
                "sample_rate": self.voice.sample_rate,
                "record_seconds": self.voice.record_seconds,
                "silence_threshold": self.voice.silence_threshold,
                "min_speech_seconds": self.voice.min_speech_seconds,
                "silence_timeout_seconds": self.voice.silence_timeout_seconds,
                "whisper_model": self.voice.whisper_model,
                "whisper_device": self.voice.whisper_device,
                "whisper_language": self.voice.whisper_language,
                "whisper_chunk_length_s": self.voice.whisper_chunk_length_s,
                "whisper_batch_size": self.voice.whisper_batch_size,
                "kitten_model": self.voice.kitten_model,
                "voice_name": self.voice.voice_name,
                "speech_speed": self.voice.speech_speed,
                "volume": self.voice.volume,
                "push_to_talk_key": self.voice.push_to_talk_key,
                "wake_word_enabled": self.voice.wake_word_enabled,
                "wake_word": self.voice.wake_word,
                "allow_text_fallback": self.voice.allow_text_fallback,
                "keep_models_loaded": self.voice.keep_models_loaded,
                "assistant_timeout_seconds": self.voice.assistant_timeout_seconds,
                "require_wake_word": self.voice.require_wake_word,
            },
            "providers": self.providers,
            "custom_tool_configs": self.custom_tool_configs,
            "custom_skill_configs": self.custom_skill_configs,
            "mcp_servers": self.mcp_servers,
            "disabled_skills": self.disabled_skills,
            "disabled_tools": self.disabled_tools,
        }
