"""Run the NEXUS API server with `python -m server`."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("NEXUS_API_HOST", "127.0.0.1")
    port = int(os.environ.get("NEXUS_API_PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
