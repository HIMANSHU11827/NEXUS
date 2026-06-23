import os
import json
import re
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("NEXUS_SKILLS")


class NexusSkillMaster:
    _instance = None
    _SINGLETON = None

    def __new__(cls, root: Optional[str] = None):
        if cls._SINGLETON is None:
            cls._SINGLETON = super().__new__(cls)
        return cls._SINGLETON

    def __init__(self, root: Optional[str] = None):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._root = root or os.getcwd()
        skills_dir = os.path.join(self._root, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        self._skills_dir = skills_dir
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    @classmethod
    def _reset_instance(cls):
        cls._SINGLETON = None

    def _load_all(self):
        self._cache.clear()
        skills_dir = Path(self._skills_dir)
        if not skills_dir.exists():
            return
        for fpath in sorted(skills_dir.iterdir()):
            if fpath.suffix == ".md":
                try:
                    content = fpath.read_text(encoding="utf-8")
                    meta = self._parse_frontmatter(content)
                    if meta:
                        meta["filepath"] = str(fpath)
                        self._cache[meta.get("id", fpath.stem)] = meta
                except Exception:
                    pass

    def _parse_frontmatter(self, content: str) -> Optional[Dict[str, Any]]:
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if not m:
            return None
        front = m.group(1)
        body = m.group(2).strip()
        meta = {"prompt": body}
        for line in front.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip()
        return meta

    def list_skills(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": v.get("id", k),
                "name": v.get("name", k),
                "description": v.get("description", ""),
                "category": v.get("category", ""),
                "prompt": v.get("prompt", ""),
                "filepath": v.get("filepath", ""),
            }
            for k, v in self._cache.items()
        ]

    def get_active_prompt(self) -> str:
        parts = []
        for skill in self._cache.values():
            prompt = skill.get("prompt", "")
            if prompt:
                parts.append(prompt)
        return "\n\n".join(parts)

    def load_skill(self, name: str) -> bool:
        self._load_all()
        return name in self._cache

    def craft_skill(self, name: str, prompt: str) -> Dict[str, Any]:
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        fpath = Path(self._skills_dir) / f"{safe_name}.md"
        content = f"""---
id: {safe_name}
name: {name}
description: Auto-crafted skill
category: tool
---
{prompt}
"""
        fpath.write_text(content, encoding="utf-8")
        self._load_all()
        return {"id": safe_name, "name": name, "filepath": str(fpath), "created": True}

    def deep_scan(self) -> str:
        self._load_all()
        return json.dumps(self.list_skills(), indent=2)

    def delete_skill(self, name: str) -> bool:
        for skill_id, meta in list(self._cache.items()):
            if skill_id == name or meta.get("name") == name:
                fpath = meta.get("filepath")
                if fpath and os.path.exists(fpath):
                    os.remove(fpath)
                    del self._cache[skill_id]
                    return True
        return False

    def find_skill(self, name: str) -> Optional[Dict[str, Any]]:
        for skill in self._cache.values():
            if skill.get("id") == name or skill.get("name") == name:
                return skill
        return None
