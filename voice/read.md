# Voice

Voice processing pipeline — speech-to-text, text-to-speech, voice activity detection, and audio handling.

**Version:** 1.0.0

## Usage
`powershell
python -m pip install -e '.[voice]'
python -m voice_chat --warmup
`

## Components
- whisper.cpp `ggml-tiny-q5_1.bin` (STT)
- KittenTTS Nano int8 (TTS)
- Voice activity detection
