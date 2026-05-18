"""Rollback snapshots for project-local file changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import shutil
import time
from typing import Dict, Iterable, List


@dataclass
class Snapshot:
    id: str
    files: Dict[str, str]
    reason: str
    created_at: float


class RollbackManager:
    """Creates project-local backups for files before risky operations."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.snapshot_dir = os.path.join(self.root, "workspace", "rollback")
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def snapshot_files(self, paths: Iterable[str], reason: str = "") -> Snapshot:
        snapshot_id = f"rb_{int(time.time())}_{abs(hash(reason)) % 10000}"
        target_dir = os.path.join(self.snapshot_dir, snapshot_id)
        os.makedirs(target_dir, exist_ok=True)
        files: Dict[str, str] = {}
        for path in paths:
            abs_path = self._resolve(path)
            if not os.path.isfile(abs_path):
                continue
            rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
            backup = os.path.join(target_dir, rel.replace("/", "__"))
            shutil.copy2(abs_path, backup)
            files[rel] = backup
        snapshot = Snapshot(snapshot_id, files, reason, time.time())
        with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(asdict(snapshot), f, indent=2)
        return snapshot

    def restore(self, snapshot_id: str) -> int:
        manifest = os.path.join(self.snapshot_dir, snapshot_id, "manifest.json")
        if not os.path.exists(manifest):
            return 0
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        restored = 0
        for rel, backup in data.get("files", {}).items():
            dest = self._resolve(rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(backup, dest)
            restored += 1
        return restored

    def _resolve(self, path: str) -> str:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return candidate
