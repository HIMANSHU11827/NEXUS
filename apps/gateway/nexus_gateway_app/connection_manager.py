"""Connection + session management for the gateway application.

Delegates persistence to the engine's ``GatewayStateStore`` and exposes a
simple, application-level view of per-platform connection state and session
mappings. No gateway state is stored in source directories — it lives under
``~/.nexus/gateway/`` (handled by the engine).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger("NEXUS-GATEWAY-CONN")


class ConnectionManager:
    """Tracks which platforms are connected and preserves session mappings."""

    def __init__(self, supervisor=None):
        self._supervisor = supervisor
        self._sessions: Dict[str, str] = {}  # chat_id -> nexus_session_id

    def register_session(self, chat_id: str, session_id: str) -> None:
        self._sessions[chat_id] = session_id

    def resolve_session(self, chat_id: str) -> Optional[str]:
        return self._sessions.get(chat_id)

    def connected_platforms(self) -> list[str]:
        if not self._supervisor:
            return []
        out = []
        for name, rt in getattr(self._supervisor, "runtimes", {}).items():
            state = getattr(rt, "state", None)
            if state is not None and str(state).lower() in ("running", "healthy"):
                out.append(name)
        return out

    def health_snapshot(self) -> Dict[str, str]:
        if not self._supervisor:
            return {}
        snap = {}
        for name, rt in getattr(self._supervisor, "runtimes", {}).items():
            snap[name] = str(getattr(rt, "state", "unknown"))
        return snap
