import os

from tools.nexus_tools.registry import ToolRegistry
from tools.nexus_tools.vision.mediapipe_suite_tool import MediaPipeSuiteTool, TASKS


def test_capabilities_cover_requested_mediapipe_surface():
    tool = MediaPipeSuiteTool()
    caps = tool.capabilities()

    for key in [
        "body_tracking",
        "face_tracking",
        "hand_tracking",
        "holistic",
        "image_segmentation",
        "object_detection",
        "gesture_recognition",
        "image_classification",
        "image_embedding",
        "audio_classification",
        "text_classification",
        "text_embedding",
        "language_detection",
        "llm_genai_edge",
    ]:
        assert key in caps["tasks"]


def test_status_reports_model_paths_without_requiring_downloads():
    tool = MediaPipeSuiteTool()
    status = tool.status()

    assert "mediapipe" in status
    assert "tasks" in status
    object_path = status["tasks"]["object_detection"]["local_model_path"]
    assert object_path.endswith(os.path.join("models", "local", "mediapipe", "tasks", "vision", "efficientdet_lite0.tflite"))


def test_download_model_without_url_returns_clear_missing_url_message():
    tool = MediaPipeSuiteTool()
    result = tool.download_model("text_embedding")

    assert result["downloaded"] is False
    assert "No default model URL" in result["reason"]
    assert result["local_model_path"]


def test_registry_exposes_mediapipe_suite():
    ToolRegistry._reset_instance()
    ToolRegistry._initialized = False
    registry = ToolRegistry()

    assert registry.get("mediapipe_suite") is not None
    assert registry.get("mp_tasks") is registry.get("mediapipe_suite")


def test_every_task_has_stable_local_path_when_model_is_declared():
    for spec in TASKS.values():
        if spec.model_filename:
            assert spec.local_model_path.startswith(os.path.join(os.getcwd(), "models", "local", "mediapipe", "tasks"))
