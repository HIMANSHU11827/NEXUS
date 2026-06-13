from __future__ import annotations

import os
import threading
import warnings
from typing import Any, Dict

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from voice.config import VoiceSettings


class NexusWhisperSTT:
    def __init__(self, settings: VoiceSettings):
        self.settings = settings
        self._pipe = None
        self._gguf_stt = None
        self._faster_stt = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._pipe is not None or self._gguf_stt is not None or self._faster_stt is not None:
            return
        
        with self._lock:
            model_name = self._resolve_model_name(self.settings.whisper_model)
            
            # ⚡ [OPTIMIZATION]: Try faster-whisper first for maximum efficiency
            try:
                self._load_faster_whisper(model_name)
                if self._faster_stt:
                    return
            except Exception as e:
                print(f"[voice-info] Falling back from faster-whisper: {e}")

            # ⚡ Check if this is a GGUF/GGML model
            if model_name.endswith(".gguf") or model_name.endswith(".bin"):
                self._load_gguf(model_name)
                return

            try:
                # print("[voice] Loading Whisper STT Engine (torch/transformers)...")
                import torch
                from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
                # print("[voice] STT Engine libraries loaded.")
            except ImportError as exc:
                raise RuntimeError(
                    "Whisper dependencies are missing. Install: "
                    "python -m pip install \"transformers>=4.35\" accelerate torch sounddevice soundfile numpy"
                ) from exc

            device = "cuda:0" if self.settings.whisper_device == "auto" and torch.cuda.is_available() else "cpu"
            if self.settings.whisper_device not in ("auto", "", None):
                device = self.settings.whisper_device
            torch_dtype = torch.float16 if str(device).startswith("cuda") else torch.float32
            # print(f"[voice] Fetching Whisper weights for '{model_name}'...")
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_name,
                dtype=torch_dtype,
                low_cpu_mem_usage=True,
                use_safetensors=True,
            )
            # print(f"[voice] Moving STT model to {device}...")
            model.to(device)
            processor = AutoProcessor.from_pretrained(model_name)
            # print("[voice] STT Pipeline assembly complete.")
            generate_kwargs = {"task": "transcribe"}
            configured_language = str(getattr(self.settings, "whisper_language", "auto") or "auto").strip().lower()
            if configured_language not in {"", "auto", "multilingual", "detect"}:
                generate_kwargs["language"] = configured_language
            self._pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                chunk_length_s=self.settings.whisper_chunk_length_s,
                batch_size=self.settings.whisper_batch_size,
                dtype=torch_dtype,
                device=device,
                generate_kwargs=generate_kwargs,
                ignore_warning=True,
            )

    def _load_faster_whisper(self, model_name: str) -> None:
        try:
            from faster_whisper import WhisperModel
            import torch
            
            # Determine best device and compute type
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            
            # print(f"[voice] Initializing Faster-Whisper Engine ({model_name}, {compute_type})...")
            
            # Map friendly names to faster-whisper names if needed
            fw_model = model_name
            if "tiny-en.gguf" in model_name or "openai/whisper-tiny" in model_name:
                fw_model = "tiny.en"
            elif "distil-whisper" in model_name:
                fw_model = "distil-large-v3"
            
            self._faster_stt = WhisperModel(fw_model, device=device, compute_type=compute_type)
            # print("[voice] Faster-Whisper Engine Online.")
        except ImportError:
            raise ImportError("faster-whisper not installed.")
        except Exception as e:
            print(f"[voice-error] Faster-Whisper Load Failed: {e}")
            self._faster_stt = None

    def _load_gguf(self, model_path: str) -> None:
        try:
            # print(f"[voice] Initializing GGUF Whisper Engine with {os.path.basename(model_path)}...")
            from llama_cpp import Whisper
            self._gguf_stt = Whisper(model_path=model_path, verbose=False)
            # print("[voice] GGUF STT Engine Online.")
        except ImportError:
            raise RuntimeError("llama-cpp-python not found. Please install it to use GGUF voice.")
        except Exception as e:
            print(f"[voice-error] GGUF Load Failed: {e}")
            self._gguf_stt = None

    @staticmethod
    def _resolve_model_name(configured_model: str) -> str:
        model_name = str(configured_model or "").strip() or "openai/whisper-tiny"
        if not os.path.isdir(model_name):
            return model_name
        expected_files = (
            "model.safetensors",
            "pytorch_model.bin",
            "pytorch_model.bin.index.json",
        )
        if any(os.path.exists(os.path.join(model_name, filename)) for filename in expected_files):
            return model_name
        fallback = "openai/whisper-tiny"
        print(
            f"[voice-warning] Whisper model folder '{model_name}' is missing Transformer weights. "
            f"Falling back to '{fallback}'."
        )
        return fallback

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        import numpy as np
        self.load()

        # ⚡ Faster-Whisper Path
        if self._faster_stt:
            segments, _info = self._faster_stt.transcribe(
                np.asarray(audio, dtype=np.float32), 
                beam_size=1,
                vad_filter=True
            )
            return "".join([segment.text for segment in segments]).strip()

        # ⚡ GGUF Path
        if self._gguf_stt:
            # llama-cpp-python Whisper takes ndarray directly
            result = self._gguf_stt.transcribe(np.asarray(audio, dtype=np.float32))
            return "".join([segment.get("text", "") for segment in result]).strip()

        # ⚡ Transformers Path
        from transformers.utils import logging as hf_logging
        sample: Dict[str, Any] = {"array": np.asarray(audio, dtype=np.float32), "sampling_rate": sample_rate}
        previous_verbosity = hf_logging.get_verbosity()
        hf_logging.set_verbosity_error()
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*custom logits processor.*")
                warnings.filterwarnings("ignore", message=".*max_new_tokens.*max_length.*")
                warnings.filterwarnings("ignore", message=".*forced_decoder_ids.*deprecated.*")
                warnings.filterwarnings("ignore", message=".*Transcription using a multilingual Whisper.*")
                result = self._pipe(sample)
        finally:
            hf_logging.set_verbosity(previous_verbosity)
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result).strip()
