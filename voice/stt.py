from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import warnings
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus.voice.stt")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning("voice/stt.py:13 : suppressed error", exc_info=True)
        pass

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from voice.config import VoiceSettings


class STTUnavailable(RuntimeError):
    """Raised when no STT backend can service a request.

    Carries a structured ``{status, reason, backend, failures}`` payload so
    callers can report a friendly "voice unavailable (reason)" message without
    losing the per-backend error details.
    """

    def __init__(
        self,
        reason: str = "no STT backend is available",
        failures: Optional[List[dict]] = None,
        backend: Optional[str] = None,
    ):
        self.reason = reason or "no STT backend is available"
        self.failures = list(failures or [])
        self.backend = backend
        super().__init__(self.reason)

    def to_dict(self) -> dict:
        return {
            "status": "unavailable",
            "reason": self.reason,
            "backend": self.backend,
            "failures": self.failures,
        }


class _Backend:
    """Base class for an STT backend.

    Backends import their heavy dependencies lazily inside ``load()`` so that a
    missing torch/whisper/transformers never crashes ``voice.stt`` at import.
    """

    name = "_base"

    def __init__(self, settings: VoiceSettings):
        self.settings = settings
        self.engine = None
        # Once a backend is blacklisted (import error, unusable model path) it is
        # never retried on the same instance, avoiding repeated slow imports.
        self.blacklisted = False

    def load(self) -> bool:
        raise NotImplementedError

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        raise NotImplementedError


class FasterWhisperBackend(_Backend):
    name = "faster_whisper"

    def load(self) -> bool:
        try:
            import torch
            from faster_whisper import WhisperModel
        except ImportError as exc:
            self.blacklisted = True
            raise STTUnavailable("faster-whisper is not installed") from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        fw_model = self._resolve_name(self.settings.whisper_model)
        self.engine = WhisperModel(fw_model, device=device, compute_type=compute_type)
        return True

    @staticmethod
    def _resolve_name(configured_model: str) -> str:
        model_name = str(configured_model or "").strip() or "tiny.en"
        known = {
            "tiny", "tiny.en", "base", "base.en", "small", "small.en",
            "medium", "medium.en", "large", "large-v2", "large-v3",
            "distil-large-v3",
        }
        if model_name in known:
            return model_name
        low = model_name.lower()
        if "tiny-en.gguf" in low or "openai/whisper-tiny.en" in low:
            return "tiny.en"
        if "openai/whisper-tiny" in low:
            return "tiny"
        if "openai/whisper-base" in low:
            return "base"
        if "openai/whisper-small" in low:
            return "small"
        if "distil-whisper" in low:
            return "distil-large-v3"
        return "tiny.en"

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        import numpy as np

        try:
            segments, _info = self.engine.transcribe(
                np.asarray(audio, dtype=np.float32),
                beam_size=1,
                vad_filter=True,
            )
            return "".join([segment.text for segment in segments]).strip()
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ("mkl_malloc", "bad allocation", "out of memory", "std::bad_alloc")):
                # Memory pressure: retry once with the tiny model.
                self.engine = None
                self.blacklisted = False
                if self.load():
                    segments, _info = self.engine.transcribe(
                        np.asarray(audio, dtype=np.float32),
                        beam_size=1,
                        vad_filter=True,
                    )
                    return "".join([segment.text for segment in segments]).strip()
            raise


class WhisperCppBackend(_Backend):
    name = "whispercpp"

    def load(self) -> bool:
        try:
            from pywhispercpp.model import Model
        except ImportError as exc:
            self.blacklisted = True
            raise STTUnavailable("pywhispercpp is not installed") from exc

        model_path = str(self.settings.whisper_model or "").strip()
        if not (model_path.endswith(".gguf") or model_path.endswith(".bin")):
            self.blacklisted = True
            raise STTUnavailable("whisper.cpp requires a .gguf/.bin model path")
        model_dir = os.path.dirname(os.path.abspath(model_path))
        model_file = os.path.basename(model_path)
        self.engine = Model(
            model=model_file,
            models_dir=model_dir,
            redirect_whispercpp_logs_to=False,
        )
        return True

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        import numpy as np

        segments = self.engine.transcribe(
            np.asarray(audio, dtype=np.float32),
            language=str(getattr(self.settings, "whisper_language", "auto") or "auto"),
        )
        return "".join([getattr(segment, "text", str(segment)) for segment in segments]).strip()


class LlamaCppBackend(_Backend):
    name = "llama_cpp"

    def load(self) -> bool:
        try:
            from llama_cpp import Whisper
        except ImportError as exc:
            self.blacklisted = True
            raise STTUnavailable("llama-cpp-python is not installed") from exc

        model_path = str(self.settings.whisper_model or "").strip()
        if not (model_path.endswith(".gguf") or model_path.endswith(".bin")):
            self.blacklisted = True
            raise STTUnavailable("llama-cpp requires a .gguf model path")
        self.engine = Whisper(model_path=model_path, verbose=False)
        return True

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        import numpy as np

        result = self.engine.transcribe(np.asarray(audio, dtype=np.float32))
        return "".join([segment.get("text", "") for segment in result]).strip()


class TransformersBackend(_Backend):
    name = "transformers"

    def load(self) -> bool:
        try:
            import torch
            from transformers import (
                AutoModelForSpeechSeq2Seq,
                AutoProcessor,
                pipeline,
            )
        except ImportError as exc:
            self.blacklisted = True
            raise STTUnavailable(
                "Whisper dependencies are missing. Install: "
                "python -m pip install \"transformers>=4.35\" accelerate torch sounddevice soundfile numpy"
            ) from exc

        model_name = self._resolve_model_name(self.settings.whisper_model)
        device = "cuda:0" if self.settings.whisper_device == "auto" and torch.cuda.is_available() else "cpu"
        if self.settings.whisper_device not in ("auto", "", None):
            device = self.settings.whisper_device
        torch_dtype = torch.float16 if str(device).startswith("cuda") else torch.float32
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_name,
            dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        )
        model.to(device)
        processor = AutoProcessor.from_pretrained(model_name)
        generate_kwargs = {"task": "transcribe"}
        configured_language = str(getattr(self.settings, "whisper_language", "auto") or "auto").strip().lower()
        if configured_language not in {"", "auto", "multilingual", "detect"}:
            generate_kwargs["language"] = configured_language
        self.engine = pipeline(
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
        return True

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
        return "tiny.en"

    def transcribe(self, audio: Any, sample_rate: int) -> str:
        import numpy as np
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
                result = self.engine(sample)
        finally:
            hf_logging.set_verbosity(previous_verbosity)
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result).strip()


BACKEND_FACTORIES = {
    FasterWhisperBackend.name: FasterWhisperBackend,
    WhisperCppBackend.name: WhisperCppBackend,
    LlamaCppBackend.name: LlamaCppBackend,
    TransformersBackend.name: TransformersBackend,
}


class NexusWhisperSTT:
    """Speech-to-text with ordered backend failover and health tracking.

    Backends are tried in ``BACKEND_ORDER``; the first that successfully loads
    and transcribes becomes the active backend. If the active backend later
    fails, the next available backend is tried before giving up. When every
    backend fails, a structured ``STTUnavailable`` is raised.
    """

    BACKEND_ORDER = ["faster_whisper", "whispercpp", "llama_cpp", "transformers"]

    def __init__(self, settings: VoiceSettings):
        self.settings = settings
        self._lock = threading.Lock()
        self._backends: Dict[str, _Backend] = {
            name: cls(settings) for name, cls in BACKEND_FACTORIES.items()
        }
        self._active: Optional[str] = None
        self._loaded = False
        self._health: Dict[str, dict] = {
            name: {
                "name": name,
                "available": False,
                "error": None,
                "loads": 0,
                "fails": 0,
                "last_error": None,
            }
            for name in self.BACKEND_ORDER
        }

    def load(self) -> None:
        """Load the first available backend (idempotent)."""
        with self._lock:
            if self._loaded:
                return
            for name in self.BACKEND_ORDER:
                if self._load_backend_locked(name):
                    self._active = name
                    self._loaded = True
                    return
            self._loaded = True  # marked attempted; transcribe still fails over lazily

    def _load_backend(self, name: str) -> bool:
        with self._lock:
            return self._load_backend_locked(name)

    def _load_backend_locked(self, name: str) -> bool:
        backend = self._backends[name]
        if backend.engine is not None:
            return True
        if backend.blacklisted:
            return False
        try:
            if backend.load():
                self._health[name]["available"] = True
                self._health[name]["loads"] += 1
                self._health[name]["error"] = None
                return True
            backend.blacklisted = True
            self._health[name]["available"] = False
            self._health[name]["error"] = "load returned without an engine"
            return False
        except Exception as exc:
            backend.blacklisted = True
            self._health[name]["available"] = False
            self._health[name]["error"] = str(exc)
            return False

    def _candidate_order(self) -> List[str]:
        order = list(self.BACKEND_ORDER)
        if self._active and self._active in order:
            order.remove(self._active)
            order.insert(0, self._active)
        return order

    def _mark_fail(self, name: str, exc: Exception) -> None:
        self._health[name]["fails"] += 1
        self._health[name]["last_error"] = str(exc)
        self._health[name]["available"] = False
        if self._active == name:
            self._active = None

    def transcribe(self, audio: Any, sample_rate: int, timeout: Optional[float] = None) -> str:
        """Transcribe ``audio``, failing over across backends with a timeout."""
        timeout = float(
            timeout
            if timeout is not None
            else getattr(self.settings, "stt_timeout_seconds", 30.0)
        )
        failures: List[dict] = []
        for name in self._candidate_order():
            backend = self._backends[name]
            if not self._load_backend(name):
                failures.append({
                    "status": "unavailable",
                    "backend": name,
                    "reason": self._health[name]["error"] or "backend could not load",
                })
                continue
            try:
                text = self._run_with_timeout(backend, audio, sample_rate, timeout)
                self._active = name
                self._health[name]["fails"] = 0
                self._health[name]["available"] = True
                return text
            except STTUnavailable as exc:
                self._mark_fail(name, exc)
                exc.backend = name
                failures.append(exc.to_dict())
            except Exception as exc:
                self._mark_fail(name, exc)
                failures.append({"status": "error", "backend": name, "reason": str(exc)})

        reason = "no STT backend is available"
        if failures:
            reasons = "; ".join(
                (f.get("reason") and str(f.get("reason"))) or str(f.get("backend", "unknown"))
                for f in failures
            )
            reason = f"voice unavailable ({reasons})"
        raise STTUnavailable(reason=reason, failures=failures)

    def _run_with_timeout(self, backend: _Backend, audio: Any, sample_rate: int, timeout: float) -> str:
        if timeout <= 0:
            return backend.transcribe(audio, sample_rate)
        result_queue: "queue.Queue[tuple]" = queue.Queue(maxsize=1)

        def _worker() -> None:
            try:
                result_queue.put(("ok", backend.transcribe(audio, sample_rate)))
            except Exception as exc:
                result_queue.put(("error", exc))

        # Daemon so a hung model can never block process shutdown.
        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        try:
            result = result_queue.get(timeout=timeout)
        except queue.Empty:
            raise STTUnavailable(
                reason=f"STT backend '{backend.name}' timed out after {timeout:.0f}s"
            )
        kind, payload = result
        worker.join(timeout=0)
        if kind == "ok":
            return payload
        raise payload

    def get_status(self) -> dict:
        """Return structured backend health/status for diagnostics."""
        return {
            "status": "ok" if self._active else "unavailable",
            "active_backend": self._active,
            "loaded": self._loaded,
            "backends": self._health,
        }