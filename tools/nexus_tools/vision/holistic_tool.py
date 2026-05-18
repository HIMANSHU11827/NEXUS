import logging
import base64
import os
from typing import Any, Dict, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class HolisticTool(BaseTool):
    """
    NEXUS VISION: GOOGLE MEDIAPIPE HOLISTIC
    Tracks 543 landmarks: Face (468), Body Pose (33), Left Hand (21), Right Hand (21).
    """

    name = "holistic"
    description = "Detects face, pose, and hand landmarks from an image using MediaPipe Holistic."
    aliases = ["mediapipe_holistic", "vision_holistic"]
    OFFICIAL_SOURCE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "nexus_mediapipe",
    )
    LOCAL_ASSET_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "models",
        "local",
        "mediapipe",
        "holistic",
    )
    DASHBOARD_ASSET_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "dashboard",
        "public",
        "mediapipe",
        "holistic",
    )

    def __init__(self):
        super().__init__()
        self._mp = None
        self._mp_holistic = None
        self._mp_drawing = None
        self._mp_drawing_styles = None
        self._cv2 = None
        self._np = None

    def _ensure_mediapipe(self):
        if self._mp_holistic is None:
            try:
                import mediapipe as mp
                import cv2
                import numpy as np

                self._mp = mp
                if not hasattr(mp, "solutions"):
                    raise ImportError(
                        "Installed mediapipe package does not expose the legacy mp.solutions API "
                        "required by official Holistic. Use the dashboard Holistic module or install "
                        "a MediaPipe build that includes mediapipe.solutions."
                    )
                self._mp_holistic = mp.solutions.holistic
                self._mp_drawing = mp.solutions.drawing_utils
                self._mp_drawing_styles = mp.solutions.drawing_styles
                self._cv2 = cv2
                self._np = np
            except ImportError as exc:
                if "does not expose the legacy mp.solutions API" in str(exc):
                    raise
                raise ImportError(
                    "MediaPipe Holistic dependencies are not installed. "
                    "Run 'python -m pip install -e .[vision]' and 'python scripts/setup_holistic.py'."
                ) from exc

    def call(self, action: str = "process_image", **kwargs) -> ToolResult:
        try:
            if action == "process_image":
                self._ensure_mediapipe()
                data = self.process_image(
                    kwargs.get("image_path") or kwargs.get("image_b64"),
                    **kwargs,
                )
                if isinstance(data, dict) and "error" in data:
                    return ToolResult(error=data["error"])
                return ToolResult(data=data)
            if action == "capabilities":
                return ToolResult(data={
                    "landmarks": 543,
                    "face_points": 468,
                    "body_pose_points": 33,
                    "hand_points": 21,
                    "supports": ["image_path", "image_b64", "dashboard_webcam"],
                    "optional_overlay": True,
                    "real_time": True,
                    "direct_outputs": [
                        "pose_landmarks",
                        "pose_world_landmarks",
                        "face_landmarks",
                        "left_hand_landmarks",
                        "right_hand_landmarks",
                        "segmentation_mask",
                    ],
                    "derived_features_need_nexus_logic": [
                        "sitting_standing",
                        "gesture_commands",
                        "avatar_rigging",
                        "emotion_clues",
                    ],
                })
            if action == "status":
                return ToolResult(data=self.status())
            if action == "source_summary":
                return ToolResult(data=self.source_summary())
            return ToolResult(error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"[HOLISTIC_ERROR]: {e}")
            return ToolResult(error=str(e))

    def process_image(self, image_source: str, **kwargs) -> Dict[str, Any]:
        try:
            if not image_source:
                return {"error": "No image source provided"}

            cv2 = self._cv2
            np = self._np

            # Decode image
            if image_source.startswith("data:image"):
                _, encoded = image_source.split(",", 1)
                data = base64.b64decode(encoded)
                nparr = np.frombuffer(data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            elif os.path.exists(image_source):
                img = cv2.imread(image_source)
            else:
                return {"error": "Invalid image source or file not found"}

            if img is None:
                return {"error": "Failed to load image"}

            static_image_mode = bool(kwargs.get("static_image_mode", True))
            model_complexity = int(kwargs.get("model_complexity", 1))
            enable_segmentation = bool(kwargs.get("enable_segmentation", False))
            refine_face_landmarks = bool(kwargs.get("refine_face_landmarks", False))
            min_detection_confidence = float(kwargs.get("min_detection_confidence", 0.5))
            min_tracking_confidence = float(kwargs.get("min_tracking_confidence", 0.5))

            # Process with MediaPipe
            with self._mp_holistic.Holistic(
                static_image_mode=static_image_mode,
                model_complexity=model_complexity,
                enable_segmentation=enable_segmentation,
                refine_face_landmarks=refine_face_landmarks,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            ) as holistic:
                results = holistic.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

                face = self._extract_landmarks(results.face_landmarks)
                pose = self._extract_landmarks(results.pose_landmarks)
                pose_world = self._extract_landmarks(results.pose_world_landmarks)
                left_hand = self._extract_landmarks(results.left_hand_landmarks)
                right_hand = self._extract_landmarks(results.right_hand_landmarks)

                output = {
                    "image": {
                        "width": int(img.shape[1]),
                        "height": int(img.shape[0]),
                    },
                    "landmark_schema": {
                        "official_total": 543,
                        "pose": 33,
                        "face": 478 if refine_face_landmarks else 468,
                        "left_hand": 21,
                        "right_hand": 21,
                        "note": "543 is the official default total; refine_face_landmarks may add iris landmarks.",
                    },
                    "detected": {
                        "face": bool(face),
                        "pose": bool(pose),
                        "left_hand": bool(left_hand),
                        "right_hand": bool(right_hand),
                    },
                    "counts": {
                        "face": len(face or []),
                        "pose": len(pose or []),
                        "pose_world": len(pose_world or []),
                        "left_hand": len(left_hand or []),
                        "right_hand": len(right_hand or []),
                    },
                    "face_landmarks": face,
                    "pose_landmarks": pose,
                    "pose_world_landmarks": pose_world,
                    "left_hand_landmarks": left_hand,
                    "right_hand_landmarks": right_hand,
                }

                if enable_segmentation and results.segmentation_mask is not None:
                    output["segmentation_mask_shape"] = list(results.segmentation_mask.shape)

                if kwargs.get("return_overlay", False):
                    annotated_image = self._draw_overlay(img, results)
                    _, buffer = cv2.imencode(".jpg", annotated_image)
                    output["overlay"] = "data:image/jpeg;base64," + base64.b64encode(buffer).decode()

                return output

        except Exception as e:
            logger.error(f"[HOLISTIC_IMAGE_ERROR]: {e}")
            return {"error": str(e)}

    def _draw_overlay(self, img, results):
        annotated_image = img.copy()
        if results.face_landmarks:
            self._mp_drawing.draw_landmarks(
                annotated_image,
                results.face_landmarks,
                self._mp_holistic.FACEMESH_TESSELATION,
                landmark_drawing_spec=None,
                connection_drawing_spec=self._mp_drawing_styles.get_default_face_mesh_tesselation_style(),
            )
        if results.pose_landmarks:
            self._mp_drawing.draw_landmarks(
                annotated_image,
                results.pose_landmarks,
                self._mp_holistic.POSE_CONNECTIONS,
                landmark_drawing_spec=self._mp_drawing_styles.get_default_pose_landmarks_style(),
            )
        if results.left_hand_landmarks:
            self._mp_drawing.draw_landmarks(
                annotated_image,
                results.left_hand_landmarks,
                self._mp_holistic.HAND_CONNECTIONS,
                connection_drawing_spec=self._mp_drawing_styles.get_default_hand_connections_style(),
            )
        if results.right_hand_landmarks:
            self._mp_drawing.draw_landmarks(
                annotated_image,
                results.right_hand_landmarks,
                self._mp_holistic.HAND_CONNECTIONS,
                connection_drawing_spec=self._mp_drawing_styles.get_default_hand_connections_style(),
            )
        return annotated_image

    def _extract_landmarks(self, landmarks):
        if not landmarks:
            return None
        return [{"x": l.x, "y": l.y, "z": l.z, "visibility": getattr(l, "visibility", 1.0)} for l in landmarks.landmark]

    def status(self) -> Dict[str, Any]:
        source_ok = os.path.isdir(self.OFFICIAL_SOURCE_PATH)
        web_assets = {
            "dashboard_asset_dir": self.DASHBOARD_ASSET_PATH,
            "holistic_js": os.path.exists(os.path.join(self.DASHBOARD_ASSET_PATH, "holistic.js")),
            "binary_graph": any(
                name.endswith(".binarypb")
                for name in os.listdir(self.DASHBOARD_ASSET_PATH)
            ) if os.path.isdir(self.DASHBOARD_ASSET_PATH) else False,
        }
        try:
            self._ensure_mediapipe()
            version = getattr(self._mp, "__version__", "unknown")
            return {
                "available": True,
                "python_legacy_solutions_available": True,
                "mediapipe_version": version,
                "official_source_path": self.OFFICIAL_SOURCE_PATH,
                "official_source_present": source_ok,
                "local_asset_path": self.LOCAL_ASSET_PATH,
                "web_assets": web_assets,
            }
        except Exception as exc:
            version = getattr(self._mp, "__version__", "unknown") if self._mp else "unknown"
            return {
                "available": False,
                "python_legacy_solutions_available": False,
                "mediapipe_version": version,
                "error": str(exc),
                "official_source_path": self.OFFICIAL_SOURCE_PATH,
                "official_source_present": source_ok,
                "local_asset_path": self.LOCAL_ASSET_PATH,
                "web_assets": web_assets,
                "dashboard_recommended": web_assets["holistic_js"],
            }

    def source_summary(self) -> Dict[str, Any]:
        docs_path = os.path.join(self.OFFICIAL_SOURCE_PATH, "docs", "solutions", "holistic.md")
        python_path = os.path.join(self.OFFICIAL_SOURCE_PATH, "mediapipe", "python", "solutions", "holistic.py")
        web_docs = os.path.join(self.OFFICIAL_SOURCE_PATH, "docs", "getting_started", "javascript.md")
        return {
            "official_repo": "https://github.com/google-ai-edge/mediapipe",
            "local_repo": self.OFFICIAL_SOURCE_PATH,
            "docs": docs_path,
            "python_solution_source": python_path,
            "javascript_setup_docs": web_docs,
            "model": "MediaPipe Holistic legacy Solution",
            "landmarks": {
                "total": 543,
                "pose": 33,
                "face": 468,
                "left_hand": 21,
                "right_hand": 21,
            },
            "pipeline": "pose detection first, then face and hand ROI crops, then merge landmarks.",
        }

    def is_read_only(self, input_data: Optional[Dict[str, Any]] = None) -> bool:
        return True

    def get_schema(self) -> Dict[str, Any]:
        schema = super().get_schema()
        schema["input_schema"] = {
            "action": "process_image | capabilities | status | source_summary",
            "image_path": "Optional path to a local image.",
            "image_b64": "Optional data:image/...;base64 payload.",
            "return_overlay": "Optional bool; include annotated JPEG data URL.",
            "model_complexity": "Optional 0, 1, or 2.",
            "enable_segmentation": "Optional bool.",
            "refine_face_landmarks": "Optional bool.",
            "min_detection_confidence": "Optional float 0.0-1.0.",
            "min_tracking_confidence": "Optional float 0.0-1.0.",
        }
        return schema
