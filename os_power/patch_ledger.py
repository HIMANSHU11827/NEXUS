"""Durable patch ledger for autonomous edits.

The ledger works even when the workspace is not a Git repository. It records
file hashes and compact diffs so autonomous changes are inspectable and can be
associated with rollback snapshots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import difflib
import hashlib
import json
import os
import time
from typing import Dict, Iterable, List, Optional


@dataclass
class FileChange:
    path: str
    before_hash: str
    after_hash: str
    diff: str


@dataclass
class PatchRecord:
    id: str
    reason: str
    files: List[FileChange] = field(default_factory=list)
    rollback_id: str = ""
    created_at: float = field(default_factory=time.time)


class PatchLedger:
    """Append-only project-local patch ledger."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.ledger_path = os.path.join(self.root, "workspace", "patch_ledger.jsonl")
        self.baseline_dir = os.path.join(self.root, "workspace", "patch_baselines")
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        os.makedirs(self.baseline_dir, exist_ok=True)

    def baseline(self, paths: Iterable[str], label: str = "") -> Dict[str, str]:
        baseline_id = f"base_{int(time.time())}_{abs(hash(label)) % 10000}"
        target = os.path.join(self.baseline_dir, baseline_id)
        os.makedirs(target, exist_ok=True)
        captured: Dict[str, str] = {}
        for path in paths:
            abs_path = self._resolve(path)
            if not os.path.isfile(abs_path):
                continue
            rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            base_path = os.path.join(target, rel.replace("/", "__"))
            with open(base_path, "w", encoding="utf-8") as f:
                f.write(content)
            captured[rel] = base_path
        with open(os.path.join(target, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"id": baseline_id, "files": captured, "label": label, "created_at": time.time()}, f, indent=2)
        return {"id": baseline_id, **captured}

    def record(self, baseline_id: str, paths: Iterable[str], reason: str = "", rollback_id: str = "") -> PatchRecord:
        manifest_path = os.path.join(self.baseline_dir, baseline_id, "manifest.json")
        if not os.path.exists(manifest_path):
            raise ValueError(f"Baseline not found: {baseline_id}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        baseline_files: Dict[str, str] = manifest.get("files", {})
        changes: List[FileChange] = []
        for path in paths:
            abs_path = self._resolve(path)
            rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
            before_path = baseline_files.get(rel)
            if not before_path or not os.path.exists(before_path):
                continue
            before = self._read_text(before_path)
            after = self._read_text(abs_path) if os.path.exists(abs_path) else ""
            changes.append(
                FileChange(
                    path=rel,
                    before_hash=self._sha(before),
                    after_hash=self._sha(after),
                    diff=self._diff(rel, before, after),
                )
            )
        record = PatchRecord(
            id=f"patch_{int(time.time())}_{abs(hash(reason)) % 10000}",
            reason=reason,
            files=changes,
            rollback_id=rollback_id,
        )
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record

    def recent(self, limit: int = 20) -> List[Dict[str, object]]:
        if not os.path.exists(self.ledger_path):
            return []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        records: List[Dict[str, object]] = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def _resolve(self, path: str) -> str:
        candidate = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes project root: {path}")
        return candidate

    @staticmethod
    def _read_text(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _diff(path: str, before: str, after: str) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{path}:before",
                tofile=f"{path}:after",
            )
        )
