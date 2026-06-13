"""Compatibility entry point for the canonical :mod:`mcp.server` module."""

from mcp.server import handle_request, main

__all__ = ["handle_request", "main"]


if __name__ == "__main__":
    main()
