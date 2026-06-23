"""KnowledgeForge — creates structured knowledge artifacts from research."""
__version__ = "1.0.0"
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from evolution.version.scripts.version import VersionManager
from providers.router import ModelRouter
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

    def forge(self, topic: str, content: str = "", key_concepts: List[str] = None, tags: List[str] = None) -> Dict[str, Any]:
        key_concepts = key_concepts or []
        tags = tags or []
        safe_topic = topic.strip().lower().replace(" ", "_")[:40]
        if not safe_topic:
            return {"created": False, "error": "topic is required"}
        topic_dir = os.path.join(self.lib_dir, safe_topic)
        os.makedirs(topic_dir, exist_ok=True)
        entry = {"title": topic, "content": content, "key_concepts": key_concepts, "tags": tags, "version": "1.0.0", "created_at": time.time(), "updated_at": time.time()}
        path = os.path.join(topic_dir, "knowledge.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.info(f"[KNOWLEDGE_FORGE] Created knowledge '{safe_topic}'")
        return {"created": True, "name": safe_topic, "version": "1.0.0", "path": path}

    def refine(self, name: str, updates: Dict[str, Any] = None) -> Dict[str, Any]:
        updates = updates or {}
        topic_dir = os.path.join(self.lib_dir, name)
        path = os.path.join(topic_dir, "knowledge.json")
        if not os.path.exists(path):
            return {"created": False, "error": f"knowledge '{name}' not found"}
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "major" if updates.get("major", False) else "minor", self.root)
        if not new_ver:
            major = updates.get("major", False)
            cur = entry.get("version", "1.0.0")
            parts = cur.split(".")
            new_ver = f"{int(parts[0]) + 1}.0.0" if major else f"{parts[0]}.{int(parts[1]) + 1}.0"
        entry["version"] = new_ver
        for k in ("title", "content", "key_concepts", "tags"):
            if k in updates:
                entry[k] = updates[k]
        entry["updated_at"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        return {"created": True, "name": name, "version": new_ver, "refined": True}
