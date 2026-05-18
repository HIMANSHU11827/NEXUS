"""NEXUS OMNI ENGINE - Unified UI Automation for Browser and OS."""

from __future__ import annotations
import json
import os
import time
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import requests

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None

from core.browser_automation.mcp_client import MCPClient

logger = logging.getLogger(__name__)

class OmniUI:
    """ Unified UI engine that delegates to Browser (MCP/Playwright) or OS (pyautogui). """

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.artifact_dir = os.path.join(self.root, "workspace", "ui_automation")
        os.makedirs(self.artifact_dir, exist_ok=True)
        self._mcp_client: Optional[MCPClient] = None

    def _get_mcp_client(self) -> Optional[MCPClient]:
        if self._mcp_client:
            return self._mcp_client
        try:
            from tools.nexus_tools.registry import ToolRegistry
            registry = ToolRegistry()
            if hasattr(registry, "_mcp_clients") and "nexus-browser" in registry._mcp_clients:
                self._mcp_client = registry._mcp_clients["nexus-browser"]
                return self._mcp_client
        except Exception:
            pass
        return None

    def status(self) -> Dict[str, Any]:
        mcp = self._get_mcp_client()
        return {
            "browser_engine": "Nexus Browser Bridge" if mcp else "Playwright",
            "os_gui_enabled": pyautogui is not None,
            "os_platform": os.name,
            "artifact_dir": self.artifact_dir
        }

    # --- OS LEVEL ACTIONS ---
    def os_action(self, action: str, **kwargs) -> Dict[str, Any]:
        if not pyautogui:
            return {"ok": False, "error": "pyautogui not installed"}
        
        try:
            if action == "click":
                pyautogui.click(x=kwargs.get("x"), y=kwargs.get("y"), button=kwargs.get("button", "left"))
            elif action == "type":
                pyautogui.write(kwargs.get("text", ""), interval=kwargs.get("interval", 0.05))
            elif action == "move":
                pyautogui.moveTo(kwargs.get("x", 0), kwargs.get("y", 0), duration=kwargs.get("duration", 0.2))
            elif action == "screenshot":
                path = os.path.join(self.artifact_dir, f"os_shot_{int(time.time()*1000)}.png")
                pyautogui.screenshot(path)
                return {"ok": True, "path": path}
            else:
                return {"ok": False, "error": f"Unknown OS action: {action}"}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- BROWSER LEVEL ACTIONS ---
    def browser_action(self, action: str, **kwargs) -> Dict[str, Any]:
        mcp = self._get_mcp_client()
        if mcp:
            # MCP handles most things through call_tool
            # We'll just proxy the primary 'run_sequence' or 'navigate' here
            if action == "navigate":
                return self._call_mcp("navigate_page", {"url": kwargs.get("url")})
            elif action == "click":
                return self._call_mcp("click", kwargs)
            # Add more mappings as needed
        
        # Fallback to static fetch if it's a simple URL get
        if action == "fetch":
            url = kwargs.get("url")
            response = requests.get(url, timeout=20)
            return {"ok": True, "text": response.text[:8000]}
            
        return {"ok": False, "error": "No browser engine active or action unsupported"}

    def _call_mcp(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        mcp = self._get_mcp_client()
        if not mcp: return {"ok": False, "error": "No MCP"}
        try:
            result = mcp.call_tool(tool_name, args)
            if not result: return {"ok": False, "error": "No result"}
            content = result.get("content", [])
            is_error = result.get("isError", False)
            text = "\n".join([c["text"] for c in content if c.get("type") == "text"])
            return {"ok": not is_error, "data": text, "error": text if is_error else None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def run_sequence(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """ Executes a mix of OS and Browser actions. """
        results = []
        for step in steps:
            target = step.get("target", "browser").lower()
            action = step.get("action")
            params = step.get("params", {})
            
            if target == "os":
                res = self.os_action(action, **params)
            else:
                res = self.browser_action(action, **params)
            
            results.append({"step": step, "result": res})
            if not res.get("ok"):
                break
        return results
