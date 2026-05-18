import os
import platform
import psutil
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class NexusHardwareManager:
    """
    NEXUS HARDWARE ABSTRACTION LAYER (HAL) v1.0
    Provides the agent with real-time awareness of the physical host.
    """

    def __init__(self):
        self.os = platform.system()
        self.arch = platform.machine()
        self._last_stats = {}

    def get_system_load(self) -> Dict[str, Any]:
        """Returns CPU, RAM, and Battery statistics."""
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            
            stats = {
                "cpu_usage_pct": cpu_pct,
                "ram_usage_pct": ram.percent,
                "ram_available_gb": round(ram.available / (1024**3), 2),
                "battery_pct": battery.percent if battery else "A/C Power",
                "is_charging": battery.power_plugged if battery else True,
            }
            self._last_stats = stats
            return stats
        except Exception as e:
            logger.error(f"[HAL_ERROR]: Failed to poll hardware: {e}")
            return {"error": str(e)}

    def get_thermal_health(self) -> Dict[str, Any]:
        """Checks for CPU overheating (Platform dependent)."""
        health = {"status": "COOL", "temp": 0.0}
        try:
            # psutil.sensors_temperatures() is not available on all Windows setups
            # Fallback to load-based estimation if physical sensors are blocked
            temps = getattr(psutil, "sensors_temperatures", lambda: {})()
            cpu_temps = temps.get('coretemp', []) or temps.get('cpu_thermal', [])
            
            if cpu_temps:
                avg_temp = sum(t.current for t in cpu_temps) / len(cpu_temps)
                health["temp"] = avg_temp
                if avg_temp > 85: health["status"] = "CRITICAL"
                elif avg_temp > 70: health["status"] = "WARM"
            else:
                # Estimate based on load
                load = psutil.cpu_percent()
                health["status"] = "COOL" if load < 70 else "WARM"
                if load > 95: health["status"] = "CRITICAL"
        except Exception as exc:
            logger.debug("Thermal probe unavailable: %s", exc)
        return health

    def get_hardware_footprint(self) -> str:
        """Standardized string for inclusion in Super Prompt (with Thermals)."""
        stats = self.get_system_load()
        thermal = self.get_thermal_health()
        if "error" in stats:
            return "[HAL_OFFLINE]"
        
        return (f"OS: {self.os} ({self.arch}) | "
                f"CPU: {stats['cpu_usage_pct']}% | "
                f"TEMP: {thermal['status']} | "
                f"RAM: {stats['ram_usage_pct']}% ({stats['ram_available_gb']}GB Free) | "
                f"PWR: {stats['battery_pct']}% ({'Charging' if stats['is_charging'] else 'Battery'})")
