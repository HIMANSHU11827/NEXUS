# Voice

Voice processing pipeline — speech-to-text, text-to-speech, VAD, and audio handling with multiple backends.

**Version:** 2.0.0

## Usage
```powershell
python -m pip install -e '.[voice]'
python -m nexus --gui   # Voice mode available in GUI
```

## Components
- `stt.py` — `NexusWhisperSTT`: 4 backends (faster-whisper, transformers, whisper.cpp, llama-cpp) with auto-failover
- `tts.py` — `KittenTTSSpeaker`: streaming text-to-speech with sentence chunking
- `audio_io.py` — `AudioIO`: smart device discovery, Silero VAD with RMS fallback, continuous capture
- `pipeline.py` — `VoiceAssistant`: full voice interaction cycle (listen → transcribe → process → speak)
- `config.py` — `VoiceSettings`: 27 configuration fields
- Voice settings in `config/voice.yml`
