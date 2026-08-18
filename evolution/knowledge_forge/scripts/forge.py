"""KnowledgeForge â€” creates structured knowledge artifacts from research.

Redesigned (2026-08-05):
- Versioning goes through ONE path: ``VersionManager`` (``ensure``/``bump``).
- Output is validated before promotion; rejected results are not written.
- Public forge/refine are fault-isolated by ``forge_guard``.
"""
__version__ = "2.1.0"
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.quality import (
    forge_guard,
    rejected_result,
    validate_forge_output,
)
from versioning.version.scripts.version import VersionManager
from models.providers.core.router import ModelRouter

logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

KNOWLEDGE_DIR = "knowledge"
LIBRARY_DIR = "library"

class KnowledgeForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.lib_dir = os.path.join(self.root, KNOWLEDGE_DIR, LIBRARY_DIR)
        os.makedirs(self.lib_dir, exist_ok=True)

    @forge_guard("knowledge")
    def forge(self, topic: str, content: str = "", key_concepts: List[str] = None, tags: List[str] = None) -> Dict[str, Any]:
        key_concepts = key_concepts or []
        tags = tags or []
        safe_topic = topic.strip().lower().replace(" ", "_")[:40]
        if not safe_topic:
            return {"created": False, "error": "topic is required"}
        content_text = str(content or "")
        if not content_text.strip():
            return self._rejected(safe_topic, "content is empty; nothing to forge", action="forge")
        vm = VersionManager(self.root)
        version = vm.ensure(safe_topic)
        topic_dir = os.path.join(self.lib_dir, safe_topic)
        path = os.path.join(topic_dir, "knowledge.json")
        entry = {
            "title": str(topic),
            "content": content_text,
            "key_concepts": key_concepts,
            "tags": tags,
            "version": version,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        check = validate_forge_output("knowledge", entry, root=self.root, write_path=path)
        if not check["valid"]:
            return self._rejected(safe_topic, check["reason"], action="forge")
        os.makedirs(topic_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.info(f"[KNOWLEDGE_FORGE] Created knowledge '{safe_topic}'")
        self._audit(safe_topic, "forge", old_version=None, new_version=version,
                    rollback_info={"kind": "knowledge", "path": path, "dir": topic_dir},
                    evidence=f"created knowledge '{safe_topic}'")
        return {"created": True, "name": safe_topic, "version": version, "path": path,
                "status": "ok", "promoted": True}

    @forge_guard("knowledge")
    def refine(self, name: str, updates: Dict[str, Any] = None) -> Dict[str, Any]:
        updates = updates or {}
        topic_dir = os.path.join(self.lib_dir, name)
        path = os.path.join(topic_dir, "knowledge.json")
        if not os.path.exists(path):
            return {"created": False, "error": f"knowledge '{name}' not found"}
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        cur = str(entry.get("version") or "1.0.0")
        content_after = str(updates.get("content", entry.get("content", "")) or "")
        if not content_after.strip():
            return self._rejected(name, "content is empty; nothing to refine", action="refine")
        vm = VersionManager(self.root)
        part = "major" if updates.get("major", False) else "minor"
        new_ver = vm.bump(name, part, self.root, current=cur) or cur
        old_version = cur
        entry["version"] = new_ver
        for k in ("title", "content", "key_concepts", "tags"):
            if k in updates:
                entry[k] = updates[k]
        entry["updated_at"] = time.time()
        check = validate_forge_output("knowledge", entry, root=self.root, write_path=path)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="refine")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.info(f"[KNOWLEDGE_FORGE] Refined knowledge '{name}' to v{new_ver}")
        self._audit(name, "refine", old_version=old_version, new_version=new_ver,
                    rollback_info={"kind": "knowledge", "path": path, "dir": topic_dir},
                    evidence=f"refined knowledge '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True,
                "status": "ok", "promoted": True}

    # â”€â”€ shared helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _rejected(self, name: str, reason: str, action: str = "forge") -> Dict[str, Any]:
        self._audit(name, action, old_version=None, new_version=None,
                    promoted=False, evidence=reason)
        return rejected_result("knowledge", name, reason, action=action)

    def _audit(self, name: str, action: str, *, old_version, new_version,
               promoted: bool = True, evidence: str = "",
               rollback_info: Optional[Dict] = None) -> None:
        try:
            EvolutionLedger(self.root).log_forge(
                "knowledge", name, action,
                old_version=old_version, new_version=new_version,
                evidence=evidence, tests_passed=None,
                promoted=promoted, rollback_info=rollback_info,
            )
        except Exception:
            logger.warning("evolution/knowledge_forge/scripts/forge.py: _audit suppressed error", exc_info=True)
