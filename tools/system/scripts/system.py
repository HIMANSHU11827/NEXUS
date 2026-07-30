from __future__ import annotations

__version__ = "2.0.0"
import os
import platform
import shutil
from pathlib import Path
from typing import Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class SystemTool(BaseTool):
    name = "system"
    description = "Monitor system resources, audit configuration, and run diagnostics"

    async def execute(self, action: str, target: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if action == "info":
                info = [
                    f"OS: {platform.system()} {platform.release()}",
                    f"Python: {platform.python_version()}",
                    f"Host: {platform.node()}",
                    f"CWD: {os.getcwd()}",
                ]
                return ToolResult(success=True, output="\n".join(info))

            elif action == "env":
                return ToolResult(success=True, output="\n".join(f"{k}={v}" for k, v in sorted(os.environ.items())))

            elif action == "audit":
                root = Path(self.root_dir or ".")
                files = list(root.rglob("*"))
                return ToolResult(success=True, output=f"Audit: {len(files)} files found in {root}")

            elif action == "disk":
                usage = shutil.disk_usage(target or "/")
                total_gb = usage.total / (1024**3)
                used_gb = usage.used / (1024**3)
                free_gb = usage.free / (1024**3)
                pct = usage.used / usage.total * 100
                return ToolResult(success=True, output=f"Disk: {total_gb:.1f}GB total, {used_gb:.1f}GB used ({pct:.1f}%), {free_gb:.1f}GB free")

            elif action == "process":
                import psutil
                if target:
                    procs = [p.info for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]) if target.lower() in p.info["name"].lower()]
                else:
                    procs = sorted([p.info for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"])], key=lambda p: p.get("cpu_percent", 0) or 0, reverse=True)[:20]
                lines = [f"{p['pid']:>8}  {p['name']:<30}  CPU:{p.get('cpu_percent', 0):>5.1f}%  MEM:{p.get('memory_percent', 0):>5.1f}%" for p in procs]
                header = f"{'PID':>8}  {'NAME':<30}  CPU    MEM"
                return ToolResult(success=True, output="Processes:\n" + header + "\n" + "\n".join(lines) if lines else "No matching processes found")

            return ToolResult(success=True, output=f"System action '{action}' completed")
        except ImportError:
            return ToolResult(success=False, error="psutil not installed. Run: pip install psutil")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
