import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from skills.registry import SkillRegistry

logger = logging.getLogger("NEXUS_SKILLS")


class NexusSkillMaster:
    _instance = None
    _SINGLETON = None
    _INSTANCES: Dict[str, "NexusSkillMaster"] = {}

    def __new__(cls, root: Optional[str] = None):
        resolved = os.path.abspath(root or os.getcwd())
        if resolved not in cls._INSTANCES:
            cls._INSTANCES[resolved] = super().__new__(cls)
        cls._SINGLETON = cls._INSTANCES[resolved]
        return cls._INSTANCES[resolved]

    def __init__(self, root: Optional[str] = None):
        resolved = os.path.abspath(root or os.getcwd())
        if getattr(self, "_initialized_root", "") == resolved:
            return
        self._initialized_root = resolved
        self._root = resolved
        primary = os.path.join(self._root, "skills")
        bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        # Auto-discover files in the project skills/ directory AND any
        # skills/ directory bundled alongside this module. This avoids losing
        # the registry when callers pass the wrong root or the process is
        # launched from a different working directory.
        self._search_dirs: List[str] = []
        for candidate in (primary, bundled):
            skills_dir = os.path.join(candidate, "skills") if candidate != primary else primary
            if os.path.isdir(skills_dir):
                self._search_dirs.append(skills_dir)
        if primary not in self._search_dirs:
            self._search_dirs.insert(0, primary)
        # Backward compat for code paths that expect a single dir.
        self._skills_dir = self._search_dirs[0]
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    @classmethod
    def _reset_instance(cls):
        cls._SINGLETON = None
        cls._INSTANCES.clear()

    def _load_all(self):
        self._cache.clear()
        for skill in SkillRegistry(self._root).discover():
            self._cache[skill.id] = {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "prompt": skill.prompt,
                "filepath": skill.path,
                "source": skill.source,
            }

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
        disabled = self._disabled_skill_ids()
        return [
            {
                "id": v.get("id", k),
                "name": v.get("name", k),
                "description": v.get("description", ""),
                "category": v.get("category", ""),
                "prompt": v.get("prompt", ""),
                "filepath": v.get("filepath", ""),
                "source": v.get("source", ""),
                "active": k not in disabled and str(v.get("name", k)) not in disabled,
            }
            for k, v in self._cache.items()
        ]

    def _disabled_skill_ids(self) -> set:
        config_path = Path(self._root) / "config" / "nexus_config.yaml"
        if not config_path.exists():
            return set()
        try:
            import yaml
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("Failed to read skill activation config: %s", config_path, exc_info=True)
            return set()
        if not isinstance(loaded, dict):
            return set()
        disabled = loaded.get("disabled_skills", [])
        if isinstance(disabled, dict):
            result = {str(name) for name, value in disabled.items() if value}
        elif isinstance(disabled, list):
            result = {str(name) for name in disabled}
        else:
            result = set()
        custom = loaded.get("custom_skill_configs", {})
        if isinstance(custom, dict):
            for name, meta in custom.items():
                if isinstance(meta, dict) and meta.get("active") is False:
                    result.add(str(name))
        return {item for item in result if item}

    def get_active_prompt(self) -> str:
        disabled = self._disabled_skill_ids()
        parts = []
        for skill_id, skill in self._cache.items():
            if skill_id in disabled or str(skill.get("name", skill_id)) in disabled:
                continue
            prompt = skill.get("prompt", "")
            if prompt:
                parts.append(prompt)
        return "\n\n".join(parts)

    def load_skill(self, name: str) -> bool:
        self._load_all()
        return name in self._cache

    def craft_skill(self, name: str, prompt: str) -> Dict[str, Any]:
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        fpath = Path(self._root) / ".opencode" / "skills" / safe_name / "SKILL.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
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

    def delete_skill(self, name: str, force: bool = False) -> bool:
        for skill_id, meta in list(self._cache.items()):
            if skill_id == name or meta.get("name") == name:
                fpath = meta.get("filepath")
                if fpath and os.path.exists(fpath):
                    resolved = Path(fpath).resolve()
                    crafted_root = (Path(self._root) / ".opencode" / "skills").resolve()
                    if not force:
                        try:
                            resolved.relative_to(crafted_root)
                        except ValueError:
                            logger.warning("Refusing to delete non-crafted skill without force: %s", resolved)
                            return False
                    os.remove(fpath)
                    del self._cache[skill_id]
                    return True
        return False

    def find_skill(self, name: str) -> Optional[Dict[str, Any]]:
        for skill in self._cache.values():
            if skill.get("id") == name or skill.get("name") == name:
                return skill
        return None
