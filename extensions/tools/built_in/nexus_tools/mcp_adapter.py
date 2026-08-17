"""MCP Tool Adapter — bridges MCPClient tools into the NEXUS ToolRegistry.

Allows any MCP stdio server's tools to be called through the same
ToolRegistry.execute() / stream_execute() pipeline as built-in tools.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult
from extensions.tools.built_in.nexus_tools.result import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_TIMEOUT,
    ToolCallResult,
    classify_error,
)

logger = logging.getLogger(__name__)

#: Default per-call MCP timeout (seconds), overridable via NEXUS_MCP_TOOL_TIMEOUT_S.
_DEFAULT_MCP_TIMEOUT_S = 30.0


def _mcp_timeout_default() -> float:
    """Return the default MCP tool timeout from env (min 1s, float)."""
    raw = os.environ.get("NEXUS_MCP_TOOL_TIMEOUT_S")
    if raw:
        try:
            value = float(raw)
            if value >= 1:
                return value
        except (TypeError, ValueError):
            logger.warning("Invalid NEXUS_MCP_TOOL_TIMEOUT_S=%r; using default", raw)
    return _DEFAULT_MCP_TIMEOUT_S


class MCPToolAdapter(BaseTool):
    """Adapts an MCP client tool into a BaseTool for the ToolRegistry.

    Registered via ::
        from mcp.client import MCPClient
        client = MCPClient("server.exe", [])
        client.start()
        for tool_def in client.list_tools():
            adapter = MCPToolAdapter(tool_def["name"], client, tool_def)
            registry._tools[tool_def["name"]] = ToolEntry(
                name=tool_def["name"],
                schema=tool_def,
                instance=adapter,
            )
    """

    def __init__(
        self,
        name: str,
        mcp_client: Any,
        tool_definition: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
    ) -> None:
        super().__init__(root_dir)
        self.name = name
        self.description = (tool_definition or {}).get("description", f"MCP tool: {name}")
        self._client = mcp_client
        self._tool_def = tool_definition or {}
        self._timeout_s = float(self._tool_def.get("timeout", _mcp_timeout_default()))

    async def execute(self, **kwargs) -> ToolResult:
        """Call the MCP tool synchronously (blocking via asyncio.to_thread)."""
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.call_tool,
                    self.name,
                    kwargs,
                ),
                timeout=self._timeout_s,
            )
            if result is None:
                return ToolCallResult(
                    name=self.name,
                    status=STATUS_ERROR,
                    error_info={"type": "ConnectionError", "message": "MCP server disconnected", "retryable": True},
                    error="MCP server disconnected",
                )
            if isinstance(result, dict) and result.get("isError") is True:
                content = result.get("content") or result.get("error") or "MCP tool reported an error"
                if isinstance(content, list):
                    error_text = "\n".join(
                        str(item.get("text", item)) if isinstance(item, dict) else str(item)
                        for item in content
                    )
                else:
                    error_text = str(content)
                return ToolCallResult(
                    name=self.name,
                    status=STATUS_ERROR,
                    error_info={"type": "MCPError", "message": error_text[:4000], "retryable": False},
                    error=error_text[:4000],
                )
            if isinstance(result, dict) and "error" in result:
                error_text = str(result["error"])
                # MCPClient reports its bounded JSON-RPC wait as a structured
                # result. Preserve timeout semantics so the registry can apply
                # retry/backoff policy instead of treating it as a permanent
                # server-side MCP error.
                if error_text.lower().startswith("timeout calling"):
                    return ToolCallResult(
                        name=self.name,
                        status=STATUS_TIMEOUT,
                        error_info={
                            "type": "TimeoutError",
                            "message": error_text[:4000],
                            "retryable": True,
                        },
                        error=error_text,
                    )
                return ToolCallResult(
                    name=self.name,
                    status=STATUS_ERROR,
                    error_info={"type": "MCPError", "message": error_text[:4000], "retryable": False},
                    error=error_text,
                )
            output = ""
            if isinstance(result, dict):
                content = result.get("content") or result.get("output") or result.get("result")
                if isinstance(content, list):
                    output = "\n".join(
                        str(item.get("text", str(item))) if isinstance(item, dict) else str(item)
                        for item in content
                    )
                elif content is not None:
                    output = str(content)
            else:
                output = str(result)
            return ToolCallResult(name=self.name, status=STATUS_OK, output=output)
        except asyncio.TimeoutError:
            return ToolCallResult(
                name=self.name,
                status=STATUS_TIMEOUT,
                error_info={"type": "TimeoutError", "message": f"MCP tool '{self.name}' timed out after {self._timeout_s}s", "retryable": True},
                error=f"Timeout after {self._timeout_s}s",
            )
        except Exception as exc:
            error_cls = classify_error(exc)
            return ToolCallResult(
                name=self.name,
                status=STATUS_ERROR,
                error_info=error_cls,
                error=str(exc),
            )

    async def stream_execute(self, **kwargs):
        """Stream from MCP tool — falls back to atomic execution."""
        result = await self.execute(**kwargs)
        yield result

    async def health_probe(self) -> bool:
        """Check if the MCP server is reachable (healthy ⇒ True)."""
        try:
            probe = self._client.health_probe()
            if isinstance(probe, str):
                return probe == "healthy"
            # Legacy bool fallback for clients without the tri-state probe.
            return bool(probe)
        except Exception:
            return False

    def is_read_only(self, params=None) -> bool:
        """MCP tools default to read-write unless specified."""
        return bool(self._tool_def.get("read_only", False))
