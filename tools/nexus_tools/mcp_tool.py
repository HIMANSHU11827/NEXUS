from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from core.browser_automation.mcp_client import MCPClient

logger = logging.getLogger(__name__)

class MCPTool(BaseTool):
    """
    A generic NEXUS tool that proxies calls to an MCP server tool.
    """

    def __init__(self, client: MCPClient, tool_def: Dict[str, Any]):
        self.client = client
        self.tool_def = tool_def
        self.name = tool_def["name"]
        self.description = tool_def.get("description", f"MCP Tool: {self.name}")
        self.aliases = []

    def call(self, **kwargs) -> ToolResult:
        try:
            result = self.client.call_tool(self.name, kwargs)
            if not result:
                return ToolResult(error=f"MCP Tool '{self.name}' returned no result")
            
            # MCP tools return { "content": [...], "isError": bool }
            content = result.get("content", [])
            is_error = result.get("isError", False)
            
            text_parts = [c["text"] for c in content if c.get("type") == "text"]
            output = "\n".join(text_parts)
            
            if is_error:
                return ToolResult(error=output)
            return ToolResult(data=output)
        except Exception as e:
            logger.exception(f"Failed to call MCP tool {self.name}")
            return ToolResult(error=str(e))

    def is_read_only(self, input_data=None):
        # We can't easily know if an MCP tool is read-only unless we analyze its name or description
        # For now, let's assume it's NOT read-only unless it sounds like a 'get' or 'list' tool.
        name = self.name.lower()
        if any(x in name for x in ["get", "list", "search", "read", "status", "take_screenshot", "take_snapshot"]):
            return True
        return False

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.tool_def.get("inputSchema", {"type": "object", "properties": {}}),
        }
