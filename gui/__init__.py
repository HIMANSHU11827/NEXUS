"""Python compatibility namespace for GUI integration tests.

The browser client lives in this directory; its HTTP API is implemented by the
FastAPI server.  Re-exporting the server keeps existing Python integrations on
one authoritative API implementation.
"""
import server as api

__all__ = ["api"]
