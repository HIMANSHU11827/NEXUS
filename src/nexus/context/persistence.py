"""NEXUS FILE-CENTRIC PERSISTENCE (v14.0)
Externalizes agent state — reasoning sessions and checkpoints — to the file
system.  Manages "infinite" state by swapping memory to disk so a long-running
agent can archive and later reload context without holding it in RAM.

Layout under ``<root>/context_archive``:
- ``<session_id>.json``          archived reasoning session
- ``<session_id>.<checkpoint>.json``  checkpoint snapshot (messages + metadata)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from nexus.runtime import safe_session_id


__version__ = "14.0.0"


class NexusFilePersistence:
    """Manages infinite state by swapping reasoning sessions to disk."""

    def __init__(self, root: str, archive_dir: str = "context_archive") -> None:
        self.root = os.path.abspath(root) if root else os.path.abspath(".")
        self.archive_dir = os.path.join(self.root, archive_dir)
        os.makedirs(self.archive_dir, exist_ok=True)

    # ─── Path helpers ────────────────────────────────────────────────

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.archive_dir, f"{safe_session_id(session_id)}.json")

    def _checkpoint_path(self, session_id: str, checkpoint_id: str) -> str:
        safe_checkpoint = re.sub(
            r"[^A-Za-z0-9_.-]", "_", os.path.basename(str(checkpoint_id or ""))
        ).strip("._")[:120] or "checkpoint"
        return os.path.join(
            self.archive_dir,
            f"{safe_session_id(session_id)}.{safe_checkpoint}.json",
        )

    # ─── Persistence API ─────────────────────────────────────────────

    def checkpoint_session(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        checkpoint_id: Optional[str] = None,
    ) -> str:
        """Dump a reasoning session to disk for infinite recall.

        Returns the path written.  ``checkpoint_id`` defaults to a timestamp.
        """
        if checkpoint_id is None:
            checkpoint_id = time.strftime("%Y%m%d%H%M%S")
        normalized_session = safe_session_id(session_id)
        normalized_checkpoint = re.sub(
            r"[^A-Za-z0-9_.-]", "_", os.path.basename(str(checkpoint_id or ""))
        ).strip("._")[:120] or "checkpoint"
        payload = {
            "session_id": normalized_session,
            "checkpoint_id": normalized_checkpoint,
            "ts": time.time(),
            "metadata": metadata or {},
            "messages": messages,
        }
        path = self._checkpoint_path(normalized_session, normalized_checkpoint)
        self._atomic_write(path, payload)
        return path

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load an archived session from disk (or None if absent)."""
        path = self._session_path(session_id)
        return self._read(path)

    def load_checkpoint(
        self, session_id: str, checkpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load a full checkpoint with messages and metadata (or None)."""
        path = self._checkpoint_path(session_id, checkpoint_id)
        return self._read(path)

    def get_context_size(self, session_id: Optional[str] = None) -> int:
        """Returns the size of the archived context in bytes."""
        if session_id:
            paths = [self._session_path(session_id)]
        else:
            try:
                paths = [
                    os.path.join(self.archive_dir, fn)
                    for fn in os.listdir(self.archive_dir)
                ]
            except OSError:
                return 0
        total = 0
        for p in paths:
            if os.path.isfile(p):
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        return total

    # ─── IO helpers ──────────────────────────────────────────────────

    def _atomic_write(self, path: str, payload: Dict[str, Any]) -> None:
        """Atomically write JSON (tmp + os.replace) to avoid corruption."""
        tmp = path + f".{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _read(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None
