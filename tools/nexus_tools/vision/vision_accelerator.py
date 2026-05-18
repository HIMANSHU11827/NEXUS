import importlib.util
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult


@dataclass(frozen=True)
class AcceleratorProvider:
    id: str
    label: str
    api: str
    device: str
    available: bool
    priority: int
    reason: str


class VisionAccelerator:
    """
    Detects native vision acceleration backends without loading heavy models.

    The browser Holistic dashboard can use WebGL today, but backend iGPU
    inference requires a native runtime such as OpenVINO or DirectML.
    """

    def __init__(self) -> None:
        self.preferred_device = os.environ.get("NEXUS_VISION_DEVICE", "GPU").upper()
        self.provider_mode = os.environ.get("NEXUS_VISION_ACCELERATOR", "auto").lower()
        self.allow_cpu_fallback = os.environ.get("NEXUS_ALLOW_CPU_FALLBACK", "true").lower() not in {
            "0",
            "false",
            "no",
        }

    def status(self) -> Dict[str, Any]:
        providers = self.providers()
        selected = self._select_provider(providers)
        return {
            "platform": {
                "system": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "gpu_adapters": self._gpu_adapters(),
            },
            "policy": {
                "preferred_device": self.preferred_device,
                "provider_mode": self.provider_mode,
                "allow_cpu_fallback": self.allow_cpu_fallback,
            },
            "selected": asdict(selected) if selected else None,
            "providers": [asdict(provider) for provider in providers],
            "live_dashboard_path": {
                "runtime": "MediaPipe Holistic web runtime",
                "acceleration": "Browser WebGL when Chrome hardware acceleration is active",
                "native_backend": bool(selected and selected.device != "CPU"),
            },
            "recommendation": self._recommendation(selected, providers),
        }

    def providers(self) -> List[AcceleratorProvider]:
        return [
            self._openvino_provider(),
            self._directml_provider(),
            self._onnx_cpu_provider(),
        ]

    def _select_provider(self, providers: List[AcceleratorProvider]) -> Optional[AcceleratorProvider]:
        allowed = [provider for provider in providers if provider.available]
        if self.provider_mode != "auto":
            allowed = [provider for provider in allowed if provider.id == self.provider_mode]
        if self.preferred_device == "GPU":
            gpu = [provider for provider in allowed if provider.device != "CPU"]
            if gpu:
                return sorted(gpu, key=lambda provider: provider.priority)[0]
            if not self.allow_cpu_fallback:
                return None
        if allowed:
            return sorted(allowed, key=lambda provider: provider.priority)[0]
        return None

    def _openvino_provider(self) -> AcceleratorProvider:
        if not self._module_exists("openvino"):
            return AcceleratorProvider(
                id="openvino",
                label="OpenVINO",
                api="OpenVINO Runtime",
                device="GPU",
                available=False,
                priority=10,
                reason="Python package not installed. Best target for Intel iGPU backend vision.",
            )
        try:
            import openvino as ov  # type: ignore

            devices = list(ov.Core().available_devices)
            gpu_devices = [device for device in devices if str(device).upper().startswith("GPU")]
            if gpu_devices:
                return AcceleratorProvider(
                    id="openvino",
                    label="OpenVINO",
                    api="OpenVINO Runtime",
                    device=gpu_devices[0],
                    available=True,
                    priority=10,
                    reason=f"Available devices: {', '.join(devices)}",
                )
            return AcceleratorProvider(
                id="openvino",
                label="OpenVINO",
                api="OpenVINO Runtime",
                device="CPU",
                available=False,
                priority=10,
                reason=f"OpenVINO installed, but no GPU device is visible. Devices: {', '.join(devices) or 'none'}",
            )
        except Exception as exc:
            return AcceleratorProvider(
                id="openvino",
                label="OpenVINO",
                api="OpenVINO Runtime",
                device="GPU",
                available=False,
                priority=10,
                reason=f"OpenVINO probe failed: {exc}",
            )

    def _directml_provider(self) -> AcceleratorProvider:
        if not self._module_exists("onnxruntime"):
            return AcceleratorProvider(
                id="directml",
                label="DirectML",
                api="ONNX Runtime DirectML EP",
                device="GPU",
                available=False,
                priority=20,
                reason="ONNX Runtime is not installed. DirectML is the Windows fallback for Intel/AMD/NVIDIA GPUs.",
            )
        try:
            import onnxruntime as ort  # type: ignore

            providers = list(ort.get_available_providers())
            available = "DmlExecutionProvider" in providers or "DirectMLExecutionProvider" in providers
            return AcceleratorProvider(
                id="directml",
                label="DirectML",
                api="ONNX Runtime DirectML EP",
                device="GPU",
                available=available,
                priority=20,
                reason=f"ONNX Runtime providers: {', '.join(providers) or 'none'}",
            )
        except Exception as exc:
            return AcceleratorProvider(
                id="directml",
                label="DirectML",
                api="ONNX Runtime DirectML EP",
                device="GPU",
                available=False,
                priority=20,
                reason=f"DirectML probe failed: {exc}",
            )

    def _onnx_cpu_provider(self) -> AcceleratorProvider:
        if not self._module_exists("onnxruntime"):
            return AcceleratorProvider(
                id="onnx_cpu",
                label="ONNX CPU",
                api="ONNX Runtime CPU EP",
                device="CPU",
                available=False,
                priority=90,
                reason="ONNX Runtime is not installed.",
            )
        try:
            import onnxruntime as ort  # type: ignore

            providers = list(ort.get_available_providers())
            return AcceleratorProvider(
                id="onnx_cpu",
                label="ONNX CPU",
                api="ONNX Runtime CPU EP",
                device="CPU",
                available="CPUExecutionProvider" in providers,
                priority=90,
                reason=f"ONNX Runtime providers: {', '.join(providers) or 'none'}",
            )
        except Exception as exc:
            return AcceleratorProvider(
                id="onnx_cpu",
                label="ONNX CPU",
                api="ONNX Runtime CPU EP",
                device="CPU",
                available=False,
                priority=90,
                reason=f"ONNX CPU probe failed: {exc}",
            )

    def _recommendation(
        self,
        selected: Optional[AcceleratorProvider],
        providers: List[AcceleratorProvider],
    ) -> str:
        if selected and selected.device != "CPU":
            return f"Native iGPU backend selected: {selected.label} on {selected.device}."
        if self._has_intel_gpu():
            return (
                "Install OpenVINO in a supported Python environment and run backend vision models through "
                "OpenVINO GPU/AUTO. Current Python 3.14 may block official wheels, so use Python 3.11/3.12 "
                "for the native iGPU runner if pip cannot install it here."
            )
        if any("DirectML" in provider.label for provider in providers):
            return "Use ONNX Runtime DirectML for a broad Windows GPU fallback, then OpenVINO where Intel iGPU is available."
        return "No native GPU provider is ready. Browser Holistic can still use WebGL, but backend inference will not be iGPU-native yet."

    def _has_intel_gpu(self) -> bool:
        return any("intel" in adapter.get("name", "").lower() for adapter in self._gpu_adapters())

    @staticmethod
    def _module_exists(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    @staticmethod
    def _gpu_adapters() -> List[Dict[str, str]]:
        if platform.system().lower() != "windows":
            return []
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterCompatibility,DriverVersion | ConvertTo-Json -Compress",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        except Exception:
            return []
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        try:
            import json

            raw = json.loads(completed.stdout)
            rows = raw if isinstance(raw, list) else [raw]
            return [
                {
                    "name": str(row.get("Name", "")),
                    "vendor": str(row.get("AdapterCompatibility", "")),
                    "driver": str(row.get("DriverVersion", "")),
                }
                for row in rows
                if isinstance(row, dict)
            ]
        except Exception:
            return []


class VisionAcceleratorTool(BaseTool):
    name = "vision_accelerator"
    description = "Reports native iGPU/GPU acceleration readiness for NEXUS vision runners."
    aliases = ["igpu_vision", "gpu_vision", "vision_gpu"]

    def call(self, action: str = "status", **kwargs) -> ToolResult:
        if action not in {"status", "providers"}:
            return ToolResult(error=f"Unknown action: {action}")
        accelerator = VisionAccelerator()
        if action == "providers":
            return ToolResult(data=[asdict(provider) for provider in accelerator.providers()])
        return ToolResult(data=accelerator.status())

    def is_read_only(self, input_data: Dict[str, Any] = None) -> bool:
        return True
