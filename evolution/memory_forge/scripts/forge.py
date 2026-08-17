"""MemoryForge — persists important cross-session context as structured memory.

Redesigned (2026-08-05):
- Versioning goes through ONE path: ``VersionManager`` (``ensure``/``bump``).
  No local fallback bumping.
- Output is validated before promotion via ``validate_forge_output``; a failed
  validation marks the result ``rejected`` (recorded in the ledger) and the
  memory is NOT written.
- Evidence honesty: empty/whitespace or provider/error-shaped evidence is
  rejected — an LLM/provider error message is never crystallized as a Learning.
- Every public forge/refine is wrapped by ``forge_guard`` so a failure returns
  a structured ``{status: failed, evidence: {stdout, stderr}}`` instead of
  raising into the runtime.
"""
__version__ = "2.1.0"
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.quality import (
    forge_guard,
    looks_like_provider_error,
    rejected_result,
    validate_forge_output,
)
from evolution.version.scripts.version import VersionManager
from providers.router import ModelRouter

logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

MEMORY_DIR = os.path.join("data", "memory_forge")

class MemoryForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.memory_dir = os.path.join(self.root, MEMORY_DIR)
        os.makedirs(self.memory_dir, exist_ok=True)

    @staticmethod
    def _safe_name(value: Any) -> str:
        """Convert a memory name into one bounded filesystem component."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip().lower())
        return safe.strip("._")[:40] or "memory"

    @forge_guard("memory")
    def forge(self, title: str, content: str = "", importance: int = 5, tags: List[str] = None) -> Dict[str, Any]:
        tags = tags or []
        if not str(title or "").strip():
            return {"created": False, "error": "title is required"}
        safe_name = self._safe_name(title).replace("-", "_")
        content_text = str(content or "")
        # V5 honesty: never crystallize empty/error-shaped evidence as a Learning.
        if not content_text.strip() or looks_like_provider_error(content_text):
            return self._rejected("memory", safe_name, "evidence rejected: empty or provider/error-shaped text is never crystallized")
        vm = VersionManager(self.root)
        version = vm.ensure(safe_name)
        payload = {
            "title": str(title),
            "content": content_text,
            "importance": int(importance),
            "tags": tags,
            "version": version,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        mem_dir = os.path.join(self.memory_dir, safe_name)
        path = os.path.join(mem_dir, "memory.json")
        check = validate_forge_output("memory", payload, root=self.root, write_path=path)
        if not check["valid"]:
            return self._rejected("memory", safe_name, check["reason"])
        os.makedirs(mem_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"[MEMORY_FORGE] Created memory '{safe_name}' (importance={importance})")
        self._audit(safe_name, "forge", old_version=None, new_version=version,
                    rollback_info={"kind": "memory", "path": path, "dir": mem_dir},
                    evidence=f"created memory '{safe_name}'")
        return {"created": True, "name": safe_name, "version": version, "path": path,
                "status": "ok", "promoted": True}

    @forge_guard("memory")
    def refine(self, name: str, updates: Dict[str, Any] = None) -> Dict[str, Any]:
        updates = updates or {}
        name = self._safe_name(name).replace("-", "_")
        mem_dir = os.path.join(self.memory_dir, name)
        path = os.path.join(mem_dir, "memory.json")
        if not os.path.exists(path):
            return {"created": False, "error": f"memory '{name}' not found"}
        with open(path, "r", encoding="utf-8") as f:
            mem = json.load(f)
        cur = str(mem.get("version") or "1.0.0")
        content_after = str(updates.get("content", mem.get("content", "")) or "")
        if not content_after.strip() or looks_like_provider_error(content_after):
            return self._rejected("memory", name, "evidence rejected: empty or provider/error-shaped text is never crystallized", action="refine")
        vm = VersionManager(self.root)
        part = "major" if updates.get("major", False) else "minor"
        new_ver = vm.bump(name, part, self.root, current=cur) or cur
        old_version = cur
        mem["version"] = new_ver
        for k in ("title", "content", "importance", "tags"):
            if k in updates:
                mem[k] = updates[k]
        mem["updated_at"] = time.time()
        check = validate_forge_output("memory", mem, root=self.root, write_path=path)
        if not check["valid"]:
            return self._rejected("memory", name, check["reason"], action="refine")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        logger.info(f"[MEMORY_FORGE] Refined memory '{name}' to v{new_ver}")
        self._audit(name, "refine", old_version=old_version, new_version=new_ver,
                    rollback_info={"kind": "memory", "path": path, "dir": mem_dir},
                    evidence=f"refined memory '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True,
                "status": "ok", "promoted": True}

    # ── shared helpers ───────────────────────────────────────────────────

    def _rejected(self, kind: str, name: str, reason: str,
                  action: str = "forge") -> Dict[str, Any]:
        self._audit(name, action, old_version=None, new_version=None,
                    promoted=False, evidence=reason)
        return rejected_result(kind, name, reason, action=action)

    def _audit(self, name: str, action: str, *, old_version, new_version,
               promoted: bool = True, evidence: str = "",
               rollback_info: Optional[Dict] = None) -> None:
        try:
            EvolutionLedger(self.root).log_forge(
                "memory", name, action,
                old_version=old_version, new_version=new_version,
                evidence=evidence, tests_passed=None,
                promoted=promoted, rollback_info=rollback_info,
            )
        except Exception:
            logger.warning("evolution/memory_forge/scripts/forge.py: _audit suppressed error", exc_info=True)
