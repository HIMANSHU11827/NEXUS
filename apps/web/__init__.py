"""Python compatibility namespace for GUI integration tests.

The browser client lives in this directory; its HTTP API is implemented by the
FastAPI server (apps.api). Re-exporting the server keeps existing Python
integrations on one authoritative API implementation.
"""
import apps.api as api

__all__ = ["api"]
