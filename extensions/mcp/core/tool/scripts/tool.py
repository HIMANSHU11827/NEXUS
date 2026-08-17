from __future__ import annotations

__version__ = "2.0.0"

import asyncio
import logging
from typing import Any, Dict, List, Optional

from extensions.mcp.core.client import MCPClient
from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)

class MCPTool(BaseTool):
    """A generic NEXUS tool that proxies calls to an MCP server tool."""

    def __init__(self, client: MCPClient, tool_def: Dict[str, Any], root_dir: Optional[str] = None):
        super().__init__(root_dir=root_dir)
        self.client = client
        self.tool_def = tool_def
        self.name = tool_def["name"]
        self.description = tool_def.get("description", f"MCP Tool: {self.name}")
        self.aliases: List[str] = []

    async def execute(self, **kwargs) -> ToolResult:
        try:
            if not self.is_available():
                return ToolResult(error=f"MCP server for tool '{self.name}' is not running")
            result = await _run_mcp_call(self.client, self.name, kwargs)
            if not result:
                return ToolResult(error=f"MCP Tool '{self.name}' returned no result")

            content = result.get("content", [])
            is_error = result.get("isError", False)

            text_parts = [c["text"] for c in content if c.get("type") == "text"]
            output = "\n".join(text_parts)

            if is_error:
                return ToolResult(error=output)
            return ToolResult(output=output)
        except Exception as e:
            logger.exception(f"Failed to call MCP tool {self.name}")
            return ToolResult(error=str(e))

    def is_read_only(self, input_data=None):
        name = self.name.lower()
        if any(x in name for x in ["get", "list", "search", "read", "status", "take_screenshot", "take_snapshot"]):
            return True
        return False

    def is_available(self) -> bool:
        checker = getattr(self.client, "is_running", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.tool_def.get("inputSchema", {"type": "object", "properties": {}}),
        }


async def _run_mcp_call(client: MCPClient, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run an MCP tool call in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(client.call_tool, tool_name, arguments)
