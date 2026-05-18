"""Minimal MCP stdio server for NEXUS code intelligence tools.

This intentionally implements the small JSON-RPC surface needed by MCP clients:
initialize, tools/list, and tools/call. It avoids extra runtime dependencies and
keeps exposed tools read-focused except for explicit graph indexing.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from core.code_intelligence.knowledge_graph import CodebaseKnowledgeGraph


SERVER_NAME = "nexus-code-graph"
PROTOCOL_VERSION = "2025-06-18"


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "nexus_code_graph_build",
            "description": "Index the current repository into the NEXUS codebase knowledge graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Repository root. Defaults to current working directory."},
                    "max_files": {"type": "integer", "default": 5000},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "nexus_code_graph_summary",
            "description": "Return graph counts, edge types, and top structural hubs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "nexus_code_graph_search",
            "description": "Search files and symbols in the indexed code graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
        {
            "name": "nexus_code_graph_dependencies",
            "description": "Show what a file, module, or symbol depends on.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["target"],
            },
        },
        {
            "name": "nexus_code_graph_dependents",
            "description": "Show what depends on a file, module, or symbol.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["target"],
            },
        },
        {
            "name": "nexus_code_graph_symbol_context",
            "description": "Return a 360-degree view of a symbol: definitions, dependencies, and dependents.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["symbol"],
            },
        },
    ]


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    root = os.path.abspath(str(arguments.get("root") or os.getcwd()))
    graph = CodebaseKnowledgeGraph(root)
    limit = int(arguments.get("limit", 20) or 20)

    if name == "nexus_code_graph_build":
        built = graph.build(max_files=int(arguments.get("max_files", 5000) or 5000))
        payload = graph.summary(built, limit=limit)
    elif name == "nexus_code_graph_summary":
        payload = graph.summary(limit=limit)
    elif name == "nexus_code_graph_search":
        payload = graph.search(str(arguments.get("query", "")), limit=limit)
    elif name == "nexus_code_graph_dependencies":
        payload = graph.dependencies(str(arguments.get("target", "")))
    elif name == "nexus_code_graph_dependents":
        payload = graph.dependents(str(arguments.get("target", "")))
    elif name == "nexus_code_graph_symbol_context":
        payload = graph.symbol_context(str(arguments.get("symbol", "")))
    else:
        raise ValueError(f"Unknown tool: {name}")

    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "isError": False,
    }


def handle_request(request: Dict[str, Any]) -> Dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": tool_definitions()}
        elif method == "tools/call":
            params = request.get("params") or {}
            result = call_tool(str(params.get("name", "")), params.get("arguments") or {})
        elif method == "notifications/initialized":
            return None
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
