"""NexusHardwareManager — truthful local hardware probing.

Uses psutil when available and degrades to the stdlib platform module
otherwise.  Every probe fails truthfully (reports unavailable) instead of
inventing numbers.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from typing import Any, Dict

logger = logging.getLogger("NEXUS_HARDWARE")

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


class NexusHardwareManager:
    """Probe CPU/memory/disk and render a compact hardware footprint line.

    Constructed with no arguments (kernel contract).  get_hardware_footprint
    is used by prompt building and never raises.
    """

    def __init__(self):
        self.psutil = psutil
        self.platform_name = platform.system() or "unknown"
        logger.info("NexusHardwareManager initialized (psutil=%s)", psutil is not None)

    # ------------------------------------------------------------------ probes

    def cpu_info(self) -> Dict[str, Any]:
        """Return CPU information; psutil-independent fields always present."""
        info: Dict[str, Any] = {
            "processor": platform.processor() or "unknown",
            "architecture": ", ".join(platform.architecture()) or "unknown",
            "logical_cores": os.cpu_count() or 0,
        }
        if self.psutil is not None:
            try:
                freq = self.psutil.cpu_freq()
                info["frequency_mhz"] = round(float(freq.current), 1) if freq and freq.current else None
                info["physical_cores"] = self.psutil.cpu_count(logical=False) or 0
                info["load_percent"] = round(float(self.psutil.cpu_percent(interval=None)), 1)
            except Exception:
                logger.warning("NexusHardwareManager.cpu probe failed", exc_info=True)
        return info

    def memory_info(self) -> Dict[str, Any]:
        """Return memory usage, or a truthful unavailable marker."""
        if self.psutil is None:
            return {"available": False, "reason": "psutil is not installed"}
        try:
            vm = self.psutil.virtual_memory()
            return {
                "available": True,
                "total_gb": round(float(vm.total) / (1024 ** 3), 2),
                "available_gb": round(float(vm.available) / (1024 ** 3), 2),
                "used_percent": round(float(vm.percent), 1),
            }
        except Exception:
            logger.warning("NexusHardwareManager.memory probe failed", exc_info=True)
            return {"available": False, "reason": "memory probe failed"}

    def disk_info(self) -> Dict[str, Any]:
        """Return disk usage for the given path (defaults to cwd)."""
        if self.psutil is None:
            return {"available": False, "reason": "psutil is not installed"}
        try:
            usage = self.psutil.disk_usage(os.getcwd())
            return {
                "available": True,
                "path": os.getcwd(),
                "total_gb": round(float(usage.total) / (1024 ** 3), 2),
                "free_gb": round(float(usage.free) / (1024 ** 3), 2),
                "used_percent": round(float(usage.percent), 1),
            }
        except Exception:
            logger.warning("NexusHardwareManager.disk probe failed", exc_info=True)
            return {"available": False, "reason": "disk probe failed"}

    def gpu_info(self) -> Dict[str, Any]:
        """Report GPU availability truthfully (requires torch + CUDA)."""
        try:
            import torch
        except Exception:
            return {"available": False, "reason": "torch not installed; cannot enumerate CUDA devices"}
        try:
            if not torch.cuda.is_available():
                return {"available": False, "reason": "no CUDA device reported by torch"}
            return {"available": True, "devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}
        except Exception:
            return {"available": False, "reason": "CUDA enumeration failed"}

    def probe(self) -> Dict[str, Any]:
        """Return a full hardware snapshot."""
        return {
            "platform": self.platform_name,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "cpu": self.cpu_info(),
            "memory": self.memory_info(),
            "disk": self.disk_info(),
            "gpu": self.gpu_info(),
        }

    # ------------------------------------------------------------------ footprint

    def get_hardware_footprint(self) -> str:
        """Return one compact hardware line for prompt grounding (never raises)."""
        try:
            cpu = self.cpu_info()
            mem = self.memory_info()
            cores = cpu.get("logical_cores") or cpu.get("physical_cores") or "?"
            if mem.get("available"):
                ram = f"{mem['total_gb']:.1f} GB"
            else:
                ram = "?"
            return f"{self.platform_name} | {cores} cores | {ram} RAM | python {sys.version_info.major}.{sys.version_info.minor}"
        except Exception:
            return f"{self.platform_name} | hardware probe unavailable"

    def summary(self) -> str:
        """Alias of get_hardware_footprint for convenience."""
        return self.get_hardware_footprint()


__all__ = ["NexusHardwareManager"]
