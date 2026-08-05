"""Evolution Ledger — tracks self-improvement metrics, forge audits, and rollback.

The ledger is the structured audit trail for the evolution forges. Every
forge create/refine appends a record via ``log_forge`` with full provenance:

    {ts, kind, name, action, old_version, new_version, evidence,
     tests_passed, promoted, rollback_info}

``rollback(kind, name)`` restores the previous version from the ledger (or
removes a freshly-created artifact when there is no prior version).
"""
__version__ = "2.1.0"
import json
import logging
import os
import re
import shutil
import time
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class EvolutionLedger:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "logs", "evolution_ledger.jsonl")
        self.summary_path = os.path.join(self.root, "logs", "evolution_summary.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, kind: str, summary: str, detail: str = "", metadata: Dict = None) -> Dict[str, Any]:
        entry = {"id": f"ev:{int(time.time())}:{hash(summary) & 0xFFFF:04x}", "kind": kind, "summary": summary, "detail": detail, "metadata": metadata or {}, "timestamp": time.time()}
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Ledger write failed: {e}")
        return entry

    def log_forge(self, kind: str, name: str, action: str,
                  old_version: Optional[str] = None,
                  new_version: Optional[str] = None,
                  evidence: Any = None,
                  tests_passed: Optional[bool] = None,
                  promoted: bool = True,
                  rollback_info: Dict = None) -> Dict[str, Any]:
        """Append a structured forge audit record (create/refine/rollback).

        This is the single write point for forge provenance. It never raises —
        a failed append is logged and the (unwritten) entry returned so callers
        can soft-degrade.
        """
        ts = time.time()
        entry = {
            "id": f"ev:{int(ts)}:{abs(hash(f'{kind}:{name}:{action}:{new_version}')) & 0xFFFF:04x}",
            "ts": ts,
            "timestamp": ts,
            "kind": kind,
            "name": name,
            "action": action,
            "old_version": old_version,
            "new_version": new_version,
            "evidence": evidence or "",
            "tests_passed": tests_passed,
            "promoted": bool(promoted),
            "rollback_info": rollback_info or {},
        }
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug(f"Ledger log_forge write failed: {e}")
        return entry

    def rollback(self, kind: str, name: str) -> Dict[str, Any]:
        """Restore an artifact to its previous version from the ledger.

        Looks up the most recent ``forge``/``refine`` ledger entry for
        (kind, name). If it has an ``old_version``, that version is written back
        into the artifact file. If the entry was a create (no prior version), the
        forged artifact directory is removed. Returns a structured dict and never
        raises. All paths are verified to stay inside the ledger root.
        """
        entries = [
            e for e in self._read_all()
            if e.get("kind") == kind and e.get("name") == name
            and e.get("action") in ("forge", "refine")
        ]
        base = {
            "action": "rollback", "kind": kind, "name": name,
        }
        if not entries:
            return {**base, "rolled_back": False, "reason": "no ledger history"}
        last = entries[-1]
        info = last.get("rollback_info") or {}
        path = info.get("path")
        if not path or not self._safe_under_root(path):
            return {**base, "rolled_back": False, "reason": "invalid rollback path"}
        old_version = last.get("old_version")
        if old_version:
            if self._restore_version_in_file(path, str(old_version), kind):
                self.log_forge(kind, name, "rollback",
                               old_version=last.get("new_version"),
                               new_version=old_version,
                               promoted=True, rollback_info=info)
                return {**base, "rolled_back": True, "restored": str(old_version), "path": path}
            return {**base, "rolled_back": False, "reason": "restore failed", "path": path}
        # Created fresh (no prior version) → fully remove the forged artifact.
        if self._remove_forged_artifact(info):
            self.log_forge(kind, name, "rollback", promoted=False, rollback_info=info)
            return {**base, "rolled_back": True, "deleted": True, "path": path}
        return {**base, "rolled_back": False, "reason": "artifact removal failed", "path": path}

    def summary(self) -> Dict[str, Any]:
        entries = self._read_all()
        by_kind = Counter(e.get("kind", "unknown") for e in entries)
        return {"total_events": len(entries), "by_kind": dict(by_kind), "applied": sum(1 for e in entries if e.get("metadata", {}).get("applied")), "active_days": len(set(e.get("timestamp", 0) // 86400 for e in entries))}

    # ── rollback helpers ─────────────────────────────────────────────────

    def _safe_under_root(self, path: str) -> bool:
        """True when ``path`` resolves inside the ledger root (no escape)."""
        try:
            root = os.path.realpath(self.root)
            target = os.path.realpath(os.path.abspath(path))
            if target == root:
                return False
            return os.path.commonpath([root, target]) == root
        except Exception:
            return False

    def _restore_version_in_file(self, path: str, version: str, kind: str) -> bool:
        """Rewrite ``version`` into the artifact file at ``path``. Best-effort."""
        try:
            if kind == "skill":
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                content = re.sub(r"version:\s*[\d.]+", f"version: {version}", content, count=1)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["version"] = version
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            logger.warning("evolution/ledger/scripts/ledger.py: _restore_version_in_file: suppressed error", exc_info=True)
            return False

    def _remove_forged_artifact(self, info: Dict) -> bool:
        """Remove a freshly-forged artifact (dir when present, else the file)."""
        artifact_dir = info.get("dir") or os.path.dirname(info.get("path", "") or "")
        path = info.get("path")
        removed_any = False
        if path and self._safe_under_root(path) and os.path.exists(path):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
                removed_any = True
            except Exception:
                logger.warning("evolution/ledger/scripts/ledger.py: _remove_forged_artifact: suppressed error", exc_info=True)
        if artifact_dir and self._safe_under_root(artifact_dir) and os.path.isdir(artifact_dir):
            try:
                shutil.rmtree(artifact_dir, ignore_errors=True)
                removed_any = True
            except Exception:
                logger.warning("evolution/ledger/scripts/ledger.py: _remove_forged_artifact(dir): suppressed error", exc_info=True)
        return removed_any

    def _read_all(self) -> List[Dict[str, Any]]:
        entries = []
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))
            except Exception:
                logger.warning("evolution/ledger/scripts/ledger.py:41 _read_all: suppressed error", exc_info=True)
                pass
        return entries
