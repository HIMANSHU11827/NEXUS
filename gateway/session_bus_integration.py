"""Gateway session bus integration — manages platform sessions."""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class GatewaySessionManager:
    """Manages gateway sessions across platforms."""

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self._sessions_dir = Path(self.root) / "gateway_sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, dict] = {}

    def resolve_session(self, platform: str, chat_id: str, user_id: Optional[str] = None) -> str:
        """Resolve a session ID. Same platform+chat gets same ID regardless of user."""
        raw = f"{platform}:{chat_id}"
        session_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        key = f"gateway_{platform}_{session_id}"
        if key not in self._cache:
            self._cache[key] = {
                "session_id": key,
                "platform": platform,
                "chat_id": chat_id,
                "user_id": user_id or "",
                "created_at": time.time(),
            }
            self._save(key)
        return key

    def get_session(self, session_id: str) -> Optional[dict]:
        if session_id in self._cache:
            return self._cache[session_id]
        path = self._sessions_dir / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self._cache[session_id] = data
                return data
            except Exception:
                pass
        return None

    def get_session_info(self, session_id: str) -> Optional[dict]:
        return self.get_session(session_id)

    def list_active_sessions(self) -> List[str]:
        return list(self._cache.keys())

    def disconnect_session(self, session_id: str):
        self._cache.pop(session_id, None)
        path = self._sessions_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def get_session_paths(self, session_id: str) -> dict:
        return {
            "memory": str(self._sessions_dir / f"{session_id}.json"),
            "work_events": str(self._sessions_dir / f"{session_id}_events.json"),
        }

    def _save(self, session_id: str):
        if session_id in self._cache:
            path = self._sessions_dir / f"{session_id}.json"
            path.write_text(json.dumps(self._cache[session_id], indent=2))

    def cleanup(self, max_age_hours: int = 24):
        now = time.time()
        cutoff = now - (max_age_hours * 3600)
        to_remove = []
        for sid, data in self._cache.items():
            if data.get("created_at", 0) < cutoff:
                to_remove.append(sid)
        for sid in to_remove:
            self.disconnect_session(sid)
