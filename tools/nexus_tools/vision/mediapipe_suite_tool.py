import importlib
import json
import logging
import os
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOCAL_TASK_ROOT = os.path.join(ROOT, "models", "local", "mediapipe", "tasks")
HOLISTIC_WEB_ASSETS = os.path.join(ROOT, "models", "local", "mediapipe", "holistic", "web_assets")


@dataclass(frozen=True)
class MediaPipeTaskSpec:
    key: str
    label: str
    domain: str
    feature: str
    module: str
    class_name: str
    method: str
    input_kind: str
    model_filename: str
    model_url: str = ""
    notes: str = ""

    @property
    def local_model_path(self) -> str:
        if not self.model_filename:
            return ""
        return os.path.join(LOCAL_TASK_ROOT, self.domain, self.model_filename)


TASKS: Dict[str, MediaPipeTaskSpec] = {
    "object_detection": MediaPipeTaskSpec(
        key="object_detection",
        label="Object Detector",
        domain="vision",
        feature="Object detection",
        module="mediapipe.tasks.python.vision.object_detector",
        class_name="ObjectDetector",
        method="detect",
        input_kind="image",
        model_filename="efficientdet_lite0.tflite",
        model_url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/latest/efficientdet_lite0.tflite",
    ),
    "gesture_recognition": MediaPipeTaskSpec(
        key="gesture_recognition",
        label="Gesture Recognizer",
        domain="vision",
        feature="Gesture recognition",
        module="mediapipe.tasks.python.vision.gesture_recognizer",
        class_name="GestureRecognizer",
        method="recognize",
        input_kind="image",
        model_filename="gesture_recognizer.task",
        model_url="https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task",
    ),
    "image_segmentation": MediaPipeTaskSpec(
        key="image_segmentation",
        label="Image Segmenter",
        domain="vision",
        feature="Image segmentation",
        module="mediapipe.tasks.python.vision.image_segmenter",
        class_name="ImageSegmenter",
        method="segment",
        input_kind="image",
        model_filename="selfie_segmenter.tflite",
        model_url="https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite",
    ),
    "image_classification": MediaPipeTaskSpec(
        key="image_classification",
        label="Image Classifier",
        domain="vision",
        feature="Image classification",
        module="mediapipe.tasks.python.vision.image_classifier",
        class_name="ImageClassifier",
        method="classify",
        input_kind="image",
        model_filename="efficientnet_lite0.tflite",
        model_url="https://storage.googleapis.com/mediapipe-models/image_classifier/efficientnet_lite0/float32/latest/efficientnet_lite0.tflite",
    ),
    "image_embedding": MediaPipeTaskSpec(
        key="image_embedding",
        label="Image Embedder",
        domain="vision",
        feature="Image embedding/search",
        module="mediapipe.tasks.python.vision.image_embedder",
        class_name="ImageEmbedder",
        method="embed",
        input_kind="image",
        model_filename="mobilenet_v3_small_075_224_embedder.tflite",
        notes="Provide a compatible MediaPipe image embedder model with model_path or add a model_url.",
    ),
    "face_detection": MediaPipeTaskSpec(
        key="face_detection",
        label="Face Detector",
        domain="vision",
        feature="Face detection",
        module="mediapipe.tasks.python.vision.face_detector",
        class_name="FaceDetector",
        method="detect",
        input_kind="image",
        model_filename="blaze_face_short_range.tflite",
        model_url="https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
    ),
    "face_tracking": MediaPipeTaskSpec(
        key="face_tracking",
        label="Face Landmarker",
        domain="vision",
        feature="Face tracking",
        module="mediapipe.tasks.python.vision.face_landmarker",
        class_name="FaceLandmarker",
        method="detect",
        input_kind="image",
        model_filename="face_landmarker.task",
        model_url="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    ),
    "hand_tracking": MediaPipeTaskSpec(
        key="hand_tracking",
        label="Hand Landmarker",
        domain="vision",
        feature="Hand tracking",
        module="mediapipe.tasks.python.vision.hand_landmarker",
        class_name="HandLandmarker",
        method="detect",
        input_kind="image",
        model_filename="hand_landmarker.task",
        model_url="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    ),
    "body_tracking": MediaPipeTaskSpec(
        key="body_tracking",
        label="Pose Landmarker",
        domain="vision",
        feature="Body tracking",
        module="mediapipe.tasks.python.vision.pose_landmarker",
        class_name="PoseLandmarker",
        method="detect",
        input_kind="image",
        model_filename="pose_landmarker_lite.task",
        model_url="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    ),
    "holistic": MediaPipeTaskSpec(
        key="holistic",
        label="Holistic",
        domain="vision",
        feature="Full body + face + hands",
        module="tools.nexus_tools.vision.holistic_tool",
        class_name="HolisticTool",
        method="dashboard_webcam",
        input_kind="webcam/gui",
        model_filename="",
        notes="NEXUS uses the official vendored MediaPipe Holistic web runtime for real-time 543-landmark webcam tracking.",
    ),
    "language_detection": MediaPipeTaskSpec(
        key="language_detection",
        label="Language Detector",
        domain="text",
        feature="Language detection",
        module="mediapipe.tasks.python.text.language_detector",
        class_name="LanguageDetector",
        method="detect",
        input_kind="text",
        model_filename="language_detector.tflite",
        notes="Add an official compatible language detector model file or pass model_path.",
    ),
    "text_classification": MediaPipeTaskSpec(
        key="text_classification",
        label="Text Classifier",
        domain="text",
        feature="Text classification",
        module="mediapipe.tasks.python.text.text_classifier",
        class_name="TextClassifier",
        method="classify",
        input_kind="text",
        model_filename="bert_text_classifier.tflite",
        notes="Requires a compatible MediaPipe text classifier model.",
    ),
    "text_embedding": MediaPipeTaskSpec(
        key="text_embedding",
        label="Text Embedder",
        domain="text",
        feature="Text embedding",
        module="mediapipe.tasks.python.text.text_embedder",
        class_name="TextEmbedder",
        method="embed",
        input_kind="text",
        model_filename="universal_sentence_encoder.tflite",
        notes="Requires a compatible MediaPipe text embedder model.",
    ),
    "audio_classification": MediaPipeTaskSpec(
        key="audio_classification",
        label="Audio Classifier",
        domain="audio",
        feature="Audio classification",
        module="mediapipe.tasks.python.audio.audio_classifier",
        class_name="AudioClassifier",
        method="classify",
        input_kind="audio",
        model_filename="yamnet_audio_classifier.tflite",
        notes="Audio runner is connected for model status/download; runtime audio tensor wiring is a follow-up.",
    ),
    "llm_genai_edge": MediaPipeTaskSpec(
        key="llm_genai_edge",
        label="MediaPipe GenAI Tasks",
        domain="genai",
        feature="LLM/GenAI edge tasks",
        module="mediapipe.tasks.python.genai",
        class_name="",
        method="setup_only",
        input_kind="model/runtime",
        model_filename="",
        notes="Tracked as a capability; use NEXUS model routing for current LLM execution.",
    ),
}


class MediaPipeSuiteTool(BaseTool):
    """
    Central connector for MediaPipe Tasks and the vendored Holistic runtime.
    """

    name = "mediapipe_suite"
    description = "Connects MediaPipe vision, text, audio, Holistic, and edge GenAI task capabilities to NEXUS."
    aliases = ["mediapipe_tasks", "mp_tasks", "vision_suite", "media_pipe"]

    def call(self, action: str = "status", **kwargs) -> ToolResult:
        try:
            if action in {"list", "capabilities"}:
                return ToolResult(data=self.capabilities())
            if action == "status":
                return ToolResult(data=self.status(kwargs.get("task")))
            if action == "download_model":
                return ToolResult(data=self.download_model(kwargs.get("task"), kwargs.get("url")))
            if action == "download_all":
                return ToolResult(data=self.download_all())
            if action == "run":
                return ToolResult(data=self.run_task(**kwargs))
            return ToolResult(error=f"Unknown action: {action}")
        except Exception as exc:
            logger.error("[MEDIAPIPE_SUITE_ERROR]: %s", exc)
            return ToolResult(error=str(exc))

    def capabilities(self) -> Dict[str, Any]:
        return {
            "model_root": LOCAL_TASK_ROOT,
            "holistic_web_assets": HOLISTIC_WEB_ASSETS,
            "tasks": {key: self._public_spec(spec) for key, spec in TASKS.items()},
            "groups": {
                "vision": [key for key, spec in TASKS.items() if spec.domain == "vision"],
                "text": [key for key, spec in TASKS.items() if spec.domain == "text"],
                "audio": [key for key, spec in TASKS.items() if spec.domain == "audio"],
                "genai": [key for key, spec in TASKS.items() if spec.domain == "genai"],
            },
        }

    def status(self, task: Optional[str] = None) -> Dict[str, Any]:
        if task:
            return self._task_status(self._get_task(task))
        return {
            "mediapipe": self._mediapipe_status(),
            "tasks": {key: self._task_status(spec) for key, spec in TASKS.items()},
        }

    def download_model(self, task: Optional[str], url: Optional[str] = None) -> Dict[str, Any]:
        spec = self._get_task(task)
        model_url = url or spec.model_url
        if not spec.model_filename:
            return {"task": spec.key, "downloaded": False, "reason": "This capability does not use a single task model file."}
        if not model_url:
            return {
                "task": spec.key,
                "downloaded": False,
                "reason": "No default model URL is configured. Pass url=... or place the model at local_model_path.",
                "local_model_path": spec.local_model_path,
            }

        os.makedirs(os.path.dirname(spec.local_model_path), exist_ok=True)
        urllib.request.urlretrieve(model_url, spec.local_model_path)
        return {
            "task": spec.key,
            "downloaded": True,
            "url": model_url,
            "local_model_path": spec.local_model_path,
            "bytes": os.path.getsize(spec.local_model_path),
        }

    def download_all(self) -> Dict[str, Any]:
        results = {}
        for key, spec in TASKS.items():
            if spec.model_url:
                results[key] = self.download_model(key)
            else:
                results[key] = {
                    "task": key,
                    "downloaded": False,
                    "reason": "No default model URL configured.",
                    "local_model_path": spec.local_model_path,
                }
        return results

    def run_task(self, **kwargs) -> Dict[str, Any]:
        spec = self._get_task(kwargs.get("task"))
        model_path = kwargs.get("model_path") or spec.local_model_path
        if spec.key == "holistic":
            return {
                "task": spec.key,
                "ready_for_gui": os.path.exists(os.path.join(HOLISTIC_WEB_ASSETS, "holistic.js")),
                "message": "Use gui Holistic webcam for real-time full body + face + hands landmarks.",
            }
        if not model_path or not os.path.exists(model_path):
            return {
                "task": spec.key,
                "error": "Model file is missing.",
                "local_model_path": model_path,
                "hint": "Run action=download_model for known models, action=download_all, or pass model_path.",
            }
        if spec.input_kind == "image":
            image_path = kwargs.get("image_path")
            if not image_path or not os.path.exists(image_path):
                return {"task": spec.key, "error": "image_path is required and must exist."}
            runner = self._create_runner(spec, model_path)
            image = self._load_mp_image(image_path)
            result = getattr(runner, spec.method)(image)
            if hasattr(runner, "close"):
                runner.close()
            return {"task": spec.key, "result": self._to_jsonable(result)}
        if spec.input_kind == "text":
            text = kwargs.get("text")
            if not text:
                return {"task": spec.key, "error": "text is required."}
            runner = self._create_runner(spec, model_path)
            result = getattr(runner, spec.method)(text)
            if hasattr(runner, "close"):
                runner.close()
            return {"task": spec.key, "result": self._to_jsonable(result)}
        return {
            "task": spec.key,
            "error": f"Runtime for input kind '{spec.input_kind}' is not implemented yet.",
            "status": self._task_status(spec),
        }

    def _create_runner(self, spec: MediaPipeTaskSpec, model_path: str) -> Any:
        module = importlib.import_module(spec.module)
        cls = getattr(module, spec.class_name)
        if hasattr(cls, "create_from_model_path"):
            return cls.create_from_model_path(model_path)
        raise RuntimeError(f"{spec.class_name} does not expose create_from_model_path on this MediaPipe build.")

    def _load_mp_image(self, image_path: str) -> Any:
        import mediapipe as mp

        return mp.Image.create_from_file(image_path)

    def _mediapipe_status(self) -> Dict[str, Any]:
        try:
            import mediapipe as mp

            return {
                "installed": True,
                "version": getattr(mp, "__version__", "unknown"),
                "has_image_api": hasattr(mp, "Image"),
                "has_legacy_solutions": hasattr(mp, "solutions"),
                "task_import_note": "Direct task module imports are used because the barrel imports can fail on this environment.",
            }
        except Exception as exc:
            return {"installed": False, "error": str(exc)}

    def _task_status(self, spec: MediaPipeTaskSpec) -> Dict[str, Any]:
        data = self._public_spec(spec)
        data["importable"] = self._module_importable(spec)
        data["model_present"] = bool(spec.local_model_path and os.path.exists(spec.local_model_path))
        if spec.key == "holistic":
            data["web_assets_present"] = os.path.exists(os.path.join(HOLISTIC_WEB_ASSETS, "holistic.js"))
        return data

    def _module_importable(self, spec: MediaPipeTaskSpec) -> bool:
        if not spec.module or spec.key == "llm_genai_edge":
            return False
        try:
            module = importlib.import_module(spec.module)
            return bool(not spec.class_name or hasattr(module, spec.class_name))
        except Exception:
            return False

    def _public_spec(self, spec: MediaPipeTaskSpec) -> Dict[str, Any]:
        data = asdict(spec)
        data["local_model_path"] = spec.local_model_path
        data["model_url_configured"] = bool(spec.model_url)
        data.pop("model_url", None)
        return data

    def _get_task(self, task: Optional[str]) -> MediaPipeTaskSpec:
        if not task:
            raise ValueError("task is required")
        key = task.strip().lower()
        if key not in TASKS:
            raise ValueError(f"Unknown MediaPipe task: {task}. Available: {sorted(TASKS)}")
        return TASKS[key]

    def _to_jsonable(self, value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=self._json_default))
        except Exception:
            return str(value)

    def _json_default(self, value: Any) -> Any:
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "__dict__"):
            return {
                key: self._to_jsonable(item)
                for key, item in value.__dict__.items()
                if not key.startswith("_")
            }
        return str(value)

    def is_read_only(self, input_data: Optional[Dict[str, Any]] = None) -> bool:
        action = (input_data or {}).get("action", "status")
        return action not in {"download_model", "download_all"}

    def get_schema(self) -> Dict[str, Any]:
        schema = super().get_schema()
        schema["input_schema"] = {
            "action": "status | capabilities | list | download_model | download_all | run",
            "task": f"One of: {', '.join(sorted(TASKS))}",
            "image_path": "For image tasks.",
            "text": "For text tasks.",
            "model_path": "Optional override path to a .task or .tflite model.",
            "url": "Optional override URL for download_model.",
        }
        return schema
