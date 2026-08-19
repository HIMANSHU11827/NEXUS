"""Workspace git snapshot — per-turn snapshots for /undo support.

Inspired by OpenAI Codex's git workspace rollback feature: every turn that
makes tool-modifying actions creates a lightweight git snapshot so the user
can undo with a single command.

Design:
- Snapshots are git commits on a temporary branch (nexus/undo).
- Each commit message includes the turn_id for traceability.
- Only created when file-mutating tools run (not for read-only turns).
- /undo reverts the workspace to the previous snapshot.
- Stale snapshots beyond a configurable window are garbage-collected.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SNAPSHOT_BRANCH = "nexus/undo"
_MAX_SNAPSHOTS = 50
_SNAPSHOT_WINDOW_HOURS = 24


@dataclass
class SnapshotRecord:
    """One workspace snapshot."""
    commit_hash: str
    turn_id: str
    timestamp: float
    message: str
    files_changed: List[str] = field(default_factory=list)


class WorkspaceSnapshot:
    """Manages per-turn git snapshots for undo support.

    Non-invasive: only operates when git is available and the workspace is a
    git repository.  All operations are wrapped in try/except so a git
    failure never disrupts the agent loop.
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self._git_available: Optional[bool] = None
        self._snapshots: List[SnapshotRecord] = []
        self._load_snapshots()

    # ── Git availability ────────────────────────────────────────────────

    def _is_git_repo(self) -> bool:
        """Return True if the workspace is a git repository."""
        if self._git_available is not None:
            return self._git_available
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            self._git_available = result.returncode == 0
        except Exception:
            self._git_available = False
        return self._git_available

    def _git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        """Run a git command in the workspace root."""
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=check,
            )
        except Exception as exc:
            logger.debug("git %s failed: %s", " ".join(args), exc)
            return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr=str(exc))

    # ── Snapshot creation ───────────────────────────────────────────────

    def has_modifying_actions(self, actions: List[Dict[str, Any]]) -> bool:
        """Return True if any action mutates the workspace."""
        write_tools = {
            "creating", "modifying", "deleting", "bash", "terminal",
            "run_command", "shell", "git_ops", "file_ops",
        }
        for action in actions:
            name = str(action.get("name") or action.get("tool") or "").lower()
            if name in write_tools:
                return True
            # Check params for write-like commands
            params = action.get("params") or {}
            command = str(params.get("command") or params.get("CommandLine") or "")
            if any(cmd in command.lower() for cmd in ("write", "create", "delete", "mv ", "rm ", "echo ", "cat >")):
                return True
        return False

    def create_snapshot(self, turn_id: str, actions: List[Dict[str, Any]]) -> Optional[SnapshotRecord]:
        """Create a git snapshot of the current workspace state.

        Only snapshots when there are file-mutating actions. Returns None
        when git is unavailable or no changes exist.
        """
        if not self._is_git_repo():
            return None
        if not actions or not self.has_modifying_actions(actions):
            return None

        # Stage all changes
        self._git("add", "-A")

        # Check if there are staged changes
        status = self._git("diff", "--cached", "--stat")
        if not status.stdout.strip():
            return None  # No changes to snapshot

        # Commit the snapshot
        message = f"nexus/undo: turn {turn_id[:12]}"
        result = self._git("commit", "-m", message, "--allow-empty")
        if result.returncode != 0:
            logger.debug("snapshot commit failed: %s", result.stderr)
            return None

        # Get the commit hash
        hash_result = self._git("rev-parse", "HEAD")
        commit_hash = hash_result.stdout.strip()
        if not commit_hash:
            return None

        # Get changed files
        files_result = self._git("diff", "--name-only", "HEAD~1", "HEAD")
        files_changed = [f for f in files_result.stdout.strip().split("\n") if f]

        record = SnapshotRecord(
            commit_hash=commit_hash,
            turn_id=turn_id,
            timestamp=time.time(),
            message=message,
            files_changed=files_changed,
        )
        self._snapshots.append(record)
        self._save_snapshots()
        self._gc_snapshots()

        logger.info("workspace snapshot created: %s (%d files)", commit_hash[:8], len(files_changed))
        return record

    # ── Undo ────────────────────────────────────────────────────────────

    def undo_last(self) -> Optional[Dict[str, Any]]:
        """Revert the workspace to the state before the most recent snapshot.

        Returns a dict with the undo result, or None when nothing to undo.
        """
        if not self._is_git_repo() or not self._snapshots:
            return None

        last = self._snapshots[-1]
        # Revert to the commit BEFORE the snapshot
        parent = f"{last.commit_hash}~1"
        result = self._git("checkout", parent, "--", ".")
        if result.returncode != 0:
            # Try reset as fallback
            result = self._git("reset", "--hard", parent)
            if result.returncode != 0:
                return {"success": False, "error": f"undo failed: {result.stderr}"}

        # Stage the revert
        self._git("add", "-A")
        revert_msg = f"nexus/undo: reverted turn {last.turn_id[:12]}"
        self._git("commit", "-m", revert_msg, "--allow-empty")

        self._snapshots.pop()
        self._save_snapshots()

        return {
            "success": True,
            "reverted_turn": last.turn_id,
            "files_reverted": last.files_changed,
            "message": f"Reverted changes from turn {last.turn_id[:12]}",
        }

    def can_undo(self) -> bool:
        """Return True if there are snapshots available to undo."""
        return bool(self._snapshots)

    # ── Snapshot persistence ────────────────────────────────────────────

    def _snapshot_path(self) -> str:
        return os.path.join(self.root_dir, ".nexus", "workspace", "snapshots.json")

    def _load_snapshots(self) -> None:
        import json
        try:
            path = self._snapshot_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._snapshots = [
                    SnapshotRecord(**item) for item in data if isinstance(item, dict)
                ]
        except Exception:
            self._snapshots = []

    def _save_snapshots(self) -> None:
        import json
        try:
            path = self._snapshot_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = [
                {
                    "commit_hash": s.commit_hash,
                    "turn_id": s.turn_id,
                    "timestamp": s.timestamp,
                    "message": s.message,
                    "files_changed": s.files_changed,
                }
                for s in self._snapshots
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.debug("snapshot save failed: %s", exc)

    def _gc_snapshots(self) -> None:
        """Remove snapshots older than the configured window."""
        cutoff = time.time() - (_SNAPSHOT_WINDOW_HOURS * 3600)
        before = len(self._snapshots)
        self._snapshots = [
            s for s in self._snapshots
            if s.timestamp > cutoff
        ]
        # Also enforce max count
        if len(self._snapshots) > _MAX_SNAPSHOTS:
            self._snapshots = self._snapshots[-_MAX_SNAPSHOTS:]
        if len(self._snapshots) != before:
            self._save_snapshots()
