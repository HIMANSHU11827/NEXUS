# NEXUS Voice Assistant

NEXUS voice mode connects local speech input, the existing NEXUS LLM loop, and local speech output:

```text
microphone -> local Distil-Whisper Large v3 -> NEXUS/LLM -> KittenTTS Micro 0.8 (40M) -> speaker
```

## Install

Core project:

```powershell
python -m pip install -e .
```

Voice extras:

```powershell
python -m pip install -e ".[voice]"
```

Recommended on Windows:

```powershell
py -3.12 -m pip install -e ".[voice]"
```

Python 3.12 or 3.13 is the safest target for the current KittenTTS dependency chain. Python 3.14 may fail on some machines because third-party speech dependencies are not consistently packaged for it yet.

If your Python installer does not accept the optional direct KittenTTS wheel, install it explicitly:

```powershell
python -m pip install "transformers>=4.35" accelerate torch sounddevice soundfile numpy keyboard
python -m pip install https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl
```

GPU is optional. Windows CPU is the default target.

## Config

Voice settings live in `configs/nexus_config.yaml`:

```yaml
voice:
  enabled: false
  auto_speak: true
  microphone_device: null
  speaker_device: null
  sample_rate: 16000
  record_seconds: 3.0
  silence_threshold: 0.01
  whisper_model: models/local/voice/distil-whisper-large-v3
  whisper_device: auto
  whisper_language: auto
  whisper_chunk_length_s: 15
  whisper_batch_size: 1
  kitten_model: KittenML/kitten-tts-micro-0.8
  voice_name: Jasper
  speech_speed: 1.0
  volume: 1.0
  push_to_talk_key: none
  wake_word_enabled: false
  wake_word: nexus
  allow_text_fallback: true
  keep_models_loaded: true
```

The default STT model is the local `models/local/voice/distil-whisper-large-v3` folder. Use `openai/whisper-tiny` for weak hardware, or switch to another local/Hugging Face Whisper-compatible model path when needed.
Set `whisper_language: auto` to let Whisper detect English, Hindi, and Hinglish-style mixed speech automatically. Set a fixed language such as `en` only if you want to force one language.

If the configured local Whisper folder is missing Transformer weight files such as `model.safetensors`, NEXUS now falls back to `openai/whisper-tiny` automatically so voice mode can still start.

KittenTTS voices include `Bella`, `Jasper`, `Luna`, `Bruno`, `Rosie`, `Hugo`, `Kiki`, and `Leo`.
KittenTTS works best for English text and usually handles Hinglish written in Roman characters reasonably well. Pure Devanagari Hindi speech output may sound less natural than English or Hinglish output.

## Run

Warm up both models, then start auto-listen voice mode:

```powershell
python voice_chat.py --warmup
```

Windows/Python 3.12 launcher:

```powershell
py -3.12 voice_chat.py --warmup
```

Windows launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_voice_chat.ps1 -Warmup
```

Typed fallback/text-only test:

```powershell
python voice_chat.py --text
```

One-turn smoke test:

```powershell
python voice_chat.py --text --once --no-speak
```

Controls:

- Default mode auto-records after each `[voice] listening...` prompt.
- In auto mode NEXUS records for `record_seconds`, then transcribes, then sends the text to the main NEXUS loop.
- Press `Ctrl+C` to stop auto-listen mode.
- Use `python voice_chat.py --manual` for the old Enter/push-to-talk behavior.
- Use `python voice_chat.py --text` to skip STT and type messages.
- In text/manual mode, type `/stop` to stop current speech playback and `/exit` to quit.

## Folder Structure

```text
core/voice/
  audio_io.py      microphone recording, speaker playback, stop support
  config.py        VoiceSettings dataclass loaded from nexus_config.yaml
  pipeline.py      microphone -> STT -> NEXUS -> TTS orchestration
  stt.py           Whisper loader/transcriber
  tts.py           KittenTTS loader, sentence chunking, speech playback
voice_chat.py      runnable CLI
docs/VOICE_ASSISTANT.md
```

## Behavior

- Whisper and KittenTTS stay loaded after first use when `keep_models_loaded: true`.
- TTS chunks long replies into sentence-sized pieces.
- New speech stops current playback before speaking, preventing overlapping audio.
- If Whisper/dependencies fail, NEXUS prompts for typed text when `allow_text_fallback: true`.
- If KittenTTS fails, NEXUS still prints the text reply.
- Wake-word mode ignores transcripts that do not contain `wake_word`.

## Troubleshooting

No microphone audio:

```powershell
python - <<'PY'
import sounddevice as sd
print(sd.query_devices())
PY
```

Set `microphone_device` or `speaker_device` to the device index shown by `sounddevice`.

KittenTTS import fails:

```powershell
python -m pip install https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl
```

Whisper is slow on CPU:

- Use `openai/whisper-tiny` or a smaller local Whisper-compatible model.
- Keep `record_seconds` near `3.0` to `5.0`.
- Keep `whisper_batch_size: 1` on CPU.
- Use a CUDA PyTorch build and set `whisper_device: auto` if you have an NVIDIA GPU.

TTS is too loud or too fast:

- Lower `volume`.
- Set `speech_speed` between `0.85` and `1.1`.

The first request is slow:

- Run `python voice_chat.py --warmup`.
- The first run downloads model files; later runs use the local cache.

## Sources

- KittenTTS Micro model card and usage: https://huggingface.co/KittenML/kitten-tts-micro-0.8
- KittenTTS repository/API notes: https://github.com/KittenML/KittenTTS
- Whisper usage and model guidance: https://github.com/openai/whisper
