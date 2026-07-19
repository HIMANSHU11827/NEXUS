"""Compatibility shim for the canonical :mod:`mcp.client` package.

The importable implementation lives in ``mcp/client/scripts/client.py``.  Keep
this path for direct-file consumers without maintaining a second transport.
"""

from mcp.client.scripts.client import MCPClient

__all__ = ["MCPClient"]
