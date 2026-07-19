"""Shared gateway session identity helpers."""

from __future__ import annotations

import hashlib
import re


def gateway_session_id(platform: str, chat_id: str) -> str:
    """Return the stable NEXUS session id for one platform chat."""
    safe_platform = re.sub(r"[^A-Za-z0-9_.-]", "_", str(platform or "gateway").strip())[:40] or "gateway"
    digest = hashlib.sha256(f"{safe_platform}:{chat_id}".encode("utf-8")).hexdigest()[:16]
    return f"gateway_{safe_platform}_{digest}"
