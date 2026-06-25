from __future__ import annotations

import os
import sys
import threading
import warnings
from typing import Any, Dict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from voice.config import VoiceSettings


class NexusWhisperSTT:
    def __init__(self, settings: VoiceSettings):
        self.settings = settings
        self._pipe = None
        self._gguf_stt = None
        self._faster_stt = None
        self._whispercpp_stt = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._pipe is not None or self._gguf_stt is not None or self._faster_stt is not None or self._whispercpp_stt is not None:
            return
        
        with self._lock:
            model_name = self._resolve_model_name(self.settings.whisper_model)

            # whisper.cpp-style quantized files should bypass faster-whisper entirely.
            if model_name.endswith(".gguf") or model_name.endswith(".bin"):
                self._load_gguf(model_name)
                return
            
            # ⚡ [OPTIMIZATION]: Try faster-whisper first for maximum efficiency
            try:
                self._load_faster_whisper(model_name)
                if self._faster_stt:
                    return
            except Exception as e:
                print(f"[voice-info] Falling back from faster-whisper: {e}")

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

            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"

            # Map HuggingFace / local paths → faster-whisper model names
            fw_model = model_name
            if model_name in {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large", "large-v2", "large-v3"}:
                fw_model = model_name  # already a valid faster-whisper name
            elif "tiny-en.gguf" in model_name or "openai/whisper-tiny.en" in model_name:
                fw_model = "tiny.en"
            elif "openai/whisper-tiny" in model_name:
                fw_model = "tiny"
            elif "openai/whisper-base" in model_name:
                fw_model = "base"
            elif "openai/whisper-small" in model_name:
                fw_model = "small"
            elif "distil-whisper" in model_name:
                fw_model = "distil-large-v3"

            print(f"[voice] Loading faster-whisper ({fw_model}, {device}/{compute_type})...")
            self._faster_stt = WhisperModel(fw_model, device=device, compute_type=compute_type)
            print(f"[voice] faster-whisper ready.")
        except ImportError:
            raise ImportError("faster-whisper not installed.")
        except Exception as e:
            print(f"[voice-error] Faster-Whisper Load Failed: {e}")
            self._faster_stt = None

    def _retry_faster_whisper_with_tiny(self) -> bool:
        try:
            print("[voice-warning] STT hit memory pressure. Retrying with faster-whisper tiny.")
            self._faster_stt = None
            self._load_faster_whisper("tiny")
            return self._faster_stt is not None
        except Exception:
            self._faster_stt = None
            return False


    def _load_gguf(self, model_path: str) -> None:
        try:
            from pywhispercpp.model import Model

            model_dir = os.path.dirname(os.path.abspath(model_path))
            model_file = os.path.basename(model_path)
            self._whispercpp_stt = Model(
                model=model_file,
                models_dir=model_dir,
                redirect_whispercpp_logs_to=False,
            )
            return
        except ImportError:
            pass
        except Exception as e:
            print(f"[voice-error] whisper.cpp Python load failed: {e}")
            self._whispercpp_stt = None

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
        model_name = str(configured_model or "").strip() or "tiny.en"
        if not os.path.isdir(model_name):
            return model_name
        expected_files = (
            "model.safetensors",
            "pytorch_model.bin",
            "pytorch_model.bin.index.json",
        )
        if any(os.path.exists(os.path.join(model_name, filename)) for filename in expected_files):
            return model_name
        fallback = "tiny.en"
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
            try:
                segments, _info = self._faster_stt.transcribe(
                    np.asarray(audio, dtype=np.float32),
                    beam_size=1,
                    vad_filter=True
                )
                return "".join([segment.text for segment in segments]).strip()
            except Exception as exc:
                message = str(exc).lower()
                if any(token in message for token in ("mkl_malloc", "bad allocation", "out of memory", "std::bad_alloc")):
                    if self._retry_faster_whisper_with_tiny():
                        segments, _info = self._faster_stt.transcribe(
                            np.asarray(audio, dtype=np.float32),
                            beam_size=1,
                            vad_filter=True
                        )
                        return "".join([segment.text for segment in segments]).strip()
                raise

        # ⚡ GGUF Path
        if self._whispercpp_stt:
            segments = self._whispercpp_stt.transcribe(
                np.asarray(audio, dtype=np.float32),
                language=str(getattr(self.settings, "whisper_language", "auto") or "auto"),
            )
            return "".join([getattr(segment, "text", str(segment)) for segment in segments]).strip()

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
