"""Local voice assistant pipeline for NEXUS."""

from apps.voice.config import VoiceSettings
from apps.voice.pipeline import VoiceAssistant
from apps.voice.stt import STTUnavailable

# Compatibility alias for the redesigned pipeline. ``VoiceAssistant`` remains
# the canonical name used by the server/GUI/TUI callers.
VoicePipeline = VoiceAssistant

__all__ = ["VoiceAssistant", "VoicePipeline", "VoiceSettings", "STTUnavailable"]
