
import os
import psutil
import time
import platform
from typing import Dict, Any
from tools.nexus_tools.base_tool import BaseTool, ToolResult

class SystemMonitorTool(BaseTool):
    """
    NEXUS SYSTEM MONITOR 1.0
    Provides real-time hardware telemetry and system health metrics.
    """
    name = "system_monitor"
    description = "Provides real-time hardware telemetry (CPU, RAM, Disk, OS) and system health metrics."

    def call(self, detailed: bool = False) -> ToolResult:
        try:
            # 1. CPU Metrics
            cpu_pct = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            # 2. Memory Metrics
            mem = psutil.virtual_memory()
            mem_total = mem.total / (1024**3)
            mem_used = mem.used / (1024**3)
            mem_pct = mem.percent
            
            # 3. Disk Metrics
            disk = psutil.disk_usage('/')
            disk_total = disk.total / (1024**3)
            disk_free = disk.free / (1024**3)
            
            # 4. OS Info
            os_info = f"{platform.system()} {platform.release()}"
            
            report = [
                "🌌 [NEXUS_HARDWARE_REPORT]",
                f"OS: {os_info}",
                f"CPU: {cpu_pct}% ({cpu_count} cores)",
                f"RAM: {mem_used:.2f}GB / {mem_total:.2f}GB ({mem_pct}%)",
                f"DISK: {disk_free:.2f}GB free / {disk_total:.2f}GB total"
            ]
            
            if detailed:
                # Add process info
                process = psutil.Process(os.getpid())
                proc_mem = process.memory_info().rss / (1024**2)
                report.append(f"NEXUS_PID: {os.getpid()}")
                report.append(f"NEXUS_MEM: {proc_mem:.2f}MB")
                
            return ToolResult(success=True, data="\n".join(report))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "detailed": {"type": "boolean", "description": "Whether to include detailed process metrics."}
                }
            }
        }
