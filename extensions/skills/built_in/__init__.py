import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .registry import SkillRegistry

logger = logging.getLogger("NEXUS_SKILLS")

#: Env override that restores legacy "inject every active skill prompt".
NEXUS_ALL_SKILLS_ENV = "NEXUS_ALL_SKILLS_INJECT"
DEFAULT_SELECTION_LIMIT = 3


def _fallback_tokenize(text: str) -> Set[str]:
    _STOPWORDS = {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with",
        "at", "by", "from", "is", "are", "was", "were", "be", "use", "using",
        "i", "you", "it", "this", "that", "please", "help", "me", "my", "not",
    }
    if not text:
        return set()
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 1}


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
            tags, required = self._parse_extra_meta(skill.path)
            self._cache[skill.id] = {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "prompt": skill.prompt,
                "filepath": skill.path,
                "source": skill.source,
                "tags": tags,
                "required": required,
            }

    @staticmethod
    def _parse_extra_meta(filepath: str) -> "tuple[list, bool]":
        """Read ``tags``/``required`` from a SKILL.md frontmatter. Never raises.

        Handles top-level ``tags: [a, b]``, ``tags: a, b``, and the nested
        ``metadata: {hermes: {tags: [...]}}`` convention used by bundled skills.
        """
        tags: List[str] = []
        required = False
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return tags, required
        m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$", content, re.DOTALL)
        if not m:
            return tags, required
        front = m.group(1)
        # Tags: accept ``tags: [a, b]``, ``tags: a, b`` and the nested
        # ``metadata: {hermes: {tags: [...]}}`` convention used by bundled skills.
        for line in front.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("tags:"):
                raw = stripped.split(":", 1)[1].strip()
                if "[" in raw:
                    inner = raw.split("[", 1)[1].split("]", 1)[0]
                    tags.extend(t.strip() for t in inner.split(",") if t.strip())
                else:
                    tags.extend(t.strip() for t in raw.split(",") if t.strip())
        req = re.findall(r"(?im)^[ \t]*required:[ \t]*(.+?)[ \t]*$", front)
        if req:
            required = req[-1].strip().strip("\"'").lower() in ("true", "yes", "1", "always")
        seen = set()
        deduped = []
        for t in tags:
            key = t.casefold()
            if key not in seen:
                seen.add(key)
                deduped.append(t)
        return deduped, required

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
        config_path = Path(self._root) / "configure" / "settings.yml"
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

    def get_active_prompt(self, task_text: Optional[str] = None, limit: int = DEFAULT_SELECTION_LIMIT) -> str:
        """Build the injected prompt block.

        With a ``task_text`` and no ``NEXUS_ALL_SKILLS_INJECT=1`` override the
        block contains only the runtime-selected skills (top-K matches plus any
        required skills). Without a task the full active-skill prompt
        concatenation is returned for backward compatibility.
        """
        selected = self.select_skills(task_text or "", limit=limit)
        return "\n\n".join(v.get("prompt", "") for v in selected if v.get("prompt"))

    # ─── Runtime selection ──────────────────────────────────────

    def select_skills(self, task_text: str = "", limit: int = DEFAULT_SELECTION_LIMIT) -> List[Dict[str, Any]]:
        """Score active skills against ``task_text`` and return at most ``limit``.

        Cheap token-overlap on frontmatter ``description`` + ``tags`` (no
        dependencies). ``required: true`` skills are always included.
        ``NEXUS_ALL_SKILLS_INJECT=1`` bypasses selection. Never raises; on error
        falls back to every active skill.
        """
        disabled = self._disabled_skill_ids()
        candidates = [
            v
            for k, v in self._cache.items()
            if k not in disabled
            and str(v.get("name", k)) not in disabled
            and v.get("prompt")
        ]
        if os.environ.get(NEXUS_ALL_SKILLS_ENV) == "1":
            return list(candidates)
        if not task_text or not str(task_text).strip():
            return list(candidates)
        try:
            required = [v for v in candidates if v.get("required")]
            pool = [v for v in candidates if not v.get("required")]
            scored = [
                (score, v)
                for score, v in ((self._score_skill(v, task_text), v) for v in pool)
                if score > 0
            ]
            scored.sort(key=lambda pair: (-pair[0], pair[1].get("name", "").casefold()))
            top = [v for score, v in scored[: max(0, limit - len(required))]]
            return list(required) + top
        except Exception:
            logger.warning("Skill selection failed; falling back to all skills", exc_info=True)
            return list(candidates)

    @staticmethod
    def _score_skill(skill: Dict[str, Any], task_text: str) -> float:
        """Token overlap between the task and the skill's description + tags + name."""
        try:
            from .engine import _tokenize
        except Exception:
            _tokenize = _fallback_tokenize
        task_tokens = _tokenize(task_text)
        if not task_tokens:
            return 0.0
        haystack = (
            f"{skill.get('description', '')} "
            f"{' '.join(skill.get('tags', []))} {skill.get('name', '')}"
        )
        skill_tokens = _tokenize(haystack)
        matched = len(task_tokens & skill_tokens) if skill_tokens else 0
        if matched == 0:
            return 0.0
        return matched * (matched / len(skill_tokens))

    def load_skill(self, name: str) -> bool:
        self._load_all()
        return name in self._cache

    def craft_skill(self, name: str, prompt: str) -> Dict[str, Any]:
        import re as _re
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        safe_name = _re.sub(r"[^a-z0-9_]", "", safe_name)[:64]
        if not safe_name:
            return {"error": "invalid skill name", "created": False}
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
