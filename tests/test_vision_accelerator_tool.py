from tools.nexus_tools.registry import ToolRegistry
from tools.nexus_tools.vision.vision_accelerator_tool import VisionAccelerator, VisionAcceleratorTool


def test_vision_accelerator_status_has_stable_shape():
    status = VisionAccelerator().status()

    assert status["policy"]["preferred_device"]
    assert "providers" in status
    assert any(provider["id"] == "openvino" for provider in status["providers"])
    assert any(provider["id"] == "directml" for provider in status["providers"])
    assert status["live_dashboard_path"]["runtime"] == "MediaPipe Holistic web runtime"


def test_vision_accelerator_tool_is_read_only():
    result = VisionAcceleratorTool().call()

    assert result.success
    assert result.data["providers"]
    assert VisionAcceleratorTool().is_read_only()


def test_registry_exposes_vision_accelerator_aliases():
    ToolRegistry._reset_instance()
    ToolRegistry._initialized = False
    registry = ToolRegistry()

    assert registry.get("vision_accelerator") is not None
    assert registry.get("igpu_vision") is registry.get("vision_accelerator")
