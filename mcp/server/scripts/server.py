"""NEXUS MCP Server — serves all NEXUS tools over stdio MCP protocol so external
clients (Claude Desktop, Cursor, etc.) can discover and call NEXUS tools.

Two-way MCP:
  - Client mode (mcp/client/): NEXUS connects to external MCP servers
  - Server mode (this): External clients connect to NEXUS as an MCP server
"""

from __future__ import annotations

__version__ = "1.0.0"

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from mcp.security import read_bounded_line

logger = logging.getLogger(__name__)

SERVER_NAME = "nexus-ai"
PROTOCOL_VERSION = "2024-11-05"


class NEXUSMCPServer:
    """MCP stdio server that serves all registered NEXUS tools."""

    def __init__(self, root_dir: str = ""):
        self.root_dir = root_dir or os.getcwd()
        self._tool_registry = None

    @property
    def tool_registry(self):
        if self._tool_registry is None:
            from tools.nexus_tools.registry import ToolRegistry
            self._tool_registry = ToolRegistry(self.root_dir)
        return self._tool_registry

    def list_tools(self) -> List[Dict[str, Any]]:
        names = self.tool_registry.list_tools()
        mcp_tools = []
        for name in names:
            tool = self.tool_registry.get(name)
            if not tool:
                continue
            schema = tool.schema
            input_schema = schema.get("parameters")
            if not isinstance(input_schema, dict):
                params = schema.get("params") if isinstance(schema.get("params"), dict) else {}
                required = [
                    param_name
                    for param_name, param_schema in params.items()
                    if isinstance(param_schema, dict) and param_schema.get("required")
                ]
                input_schema = {
                    "type": "object",
                    "properties": params,
                }
                if required:
                    input_schema["required"] = required
            mcp_tools.append({
                "name": schema.get("name", name),
                "description": schema.get("description", ""),
                "inputSchema": input_schema,
            })
        return mcp_tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.tool_registry.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        try:
            result = await tool.instance.execute(**arguments)
            text = str(result.output) if result.output else ""
            if result.error:
                return {
                    "content": [{"type": "text", "text": f"Error: {result.error}"}],
                    "isError": True,
                }
            return {
                "content": [{"type": "text", "text": text or "OK"}],
                "isError": False,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    async def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = request.get("method")
        req_id = request.get("id")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                params = request.get("params") or {}
                result = await self.call_tool(
                    str(params.get("name", "")),
                    params.get("arguments") or {},
                )
            elif method == "notifications/initialized":
                return None
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            logger.exception("MCP request handler error")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def serve_stdio(self):
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        while True:
            line, oversized = read_bounded_line(sys.stdin)
            if not line and not oversized:
                break
            if oversized:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "MCP message too large"},
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                continue
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": str(exc)},
                }
            else:
                response = asyncio.run(self.handle_request(request))
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()


def serve(root_dir: str = "") -> None:
    """Run NEXUS as an MCP stdio server."""
    server = NEXUSMCPServer(root_dir)
    server.serve_stdio()


def main() -> None:
    """Entry point for `python -m mcp.server`."""
    root = os.environ.get("NEXUS_ROOT", "")
    serve(root)


if __name__ == "__main__":
    main()
