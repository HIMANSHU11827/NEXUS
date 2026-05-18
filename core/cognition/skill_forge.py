"""Skill Forge: creates reusable local workflow definitions safely."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Dict, List


@dataclass
class ForgedSkill:
    id: str
    name: str
    description: str
    steps: List[str]
    created_at: float = field(default_factory=time.time)


class SkillForge:
    """Stores reusable macros/workflows without generating executable code by default."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "forged_skills.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.skills: Dict[str, ForgedSkill] = {}
        self._load()

    def forge(self, name: str, description: str, steps: List[str]) -> ForgedSkill:
        safe_name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "skill"
        skill = ForgedSkill(f"skill:{safe_name}", name.strip(), description.strip(), [s.strip() for s in steps if s.strip()])
        self.skills[skill.id] = skill
        self._save()
        return skill

    def search(self, query: str) -> List[ForgedSkill]:
        terms = set(query.lower().split())
        scored = []
        for skill in self.skills.values():
            haystack = f"{skill.name} {skill.description} {' '.join(skill.steps)}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [skill for _, skill in scored]

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.skills = {k: ForgedSkill(**v) for k, v in raw.items()}
        except Exception:
            self.skills = {}

    def _save(self) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.skills.items()}, f, indent=2)
        os.replace(temp, self.path)
