"""MemoryForge — persists important cross-session context as structured memory."""
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

MEMORY_DIR = "memory"

class MemoryForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.memory_dir = os.path.join(self.root, MEMORY_DIR)
        os.makedirs(self.memory_dir, exist_ok=True)

    def forge(self, title: str, content: str = "", importance: int = 5, tags: List[str] = None) -> Dict[str, Any]:
        tags = tags or []
        safe_name = title.strip().lower().replace(" ", "_").replace("-", "_")[:40]
        if not safe_name:
            return {"created": False, "error": "title is required"}
        mem_dir = os.path.join(self.memory_dir, safe_name)
        os.makedirs(mem_dir, exist_ok=True)
        mem = {"title": title, "content": content, "importance": importance, "tags": tags, "version": "1.0.0", "created_at": time.time(), "updated_at": time.time()}
        path = os.path.join(mem_dir, "memory.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        logger.info(f"[MEMORY_FORGE] Created memory '{safe_name}' (importance={importance})")
        return {"created": True, "name": safe_name, "version": "1.0.0", "path": path}

    def refine(self, name: str, updates: Dict[str, Any] = None) -> Dict[str, Any]:
        updates = updates or {}
        mem_dir = os.path.join(self.memory_dir, name)
        path = os.path.join(mem_dir, "memory.json")
        if not os.path.exists(path):
            return {"created": False, "error": f"memory '{name}' not found"}
        with open(path, "r", encoding="utf-8") as f:
            mem = json.load(f)
        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "major" if updates.get("major", False) else "minor", self.root)
        if not new_ver:
            major = updates.get("major", False)
            cur = mem.get("version", "1.0.0")
            parts = cur.split(".")
            new_ver = f"{int(parts[0]) + 1}.0.0" if major else f"{parts[0]}.{int(parts[1]) + 1}.0"
        mem["version"] = new_ver
        for k in ("title", "content", "importance", "tags"):
            if k in updates:
                mem[k] = updates[k]
        mem["updated_at"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        return {"created": True, "name": name, "version": new_ver, "refined": True}
