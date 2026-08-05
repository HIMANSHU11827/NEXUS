"""Canonical, side-effect-free NEXUS skill discovery.

``.opencode/skills/<name>/SKILL.md`` is the canonical format.  Legacy
``skills/<name>/SKILL.md`` and ``skills/<name>.md`` files remain readable, but a
canonical skill with the same id always wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str
    description: str
    version: str
    prompt: str
    path: str
    source: str

    def usage_event(self) -> Dict[str, str]:
        """Public fields for a ``skill.used`` event payload."""
        return {"name": self.name, "skill_id": self.id, "source": self.source, "path": self.path}


class SkillRegistry:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()

    def _candidates(self) -> Iterable[tuple[Path, str]]:
        canonical = self.root / ".opencode" / "skills"
        legacy = self.root / "skills"
        if canonical.is_dir():
            for path in sorted(canonical.rglob("*")):
                if path.is_file() and (path.name == "SKILL.md" or (path.parent == canonical and path.suffix.lower() == ".md")):
                    if path.name not in {"README.md", "read.md"}:
                        yield path, "opencode"
        if legacy.is_dir():
            for path in sorted(legacy.rglob("*")):
                if path.is_file() and path.name not in {"README.md", "read.md"} and (
                    path.name == "SKILL.md" or (path.parent == legacy and path.suffix.lower() == ".md")
                ):
                    yield path, "legacy"

    @staticmethod
    def _parse(path: Path, source: str) -> SkillRecord:
        content = path.read_text(encoding="utf-8")
        metadata: Dict[str, str] = {}
        body = content.strip()
        match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", content, re.DOTALL)
        if match:
            for line in match.group(1).splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip().lower()] = value.strip().strip('"\'')
            body = match.group(2).strip()
        fallback = path.parent.name if path.name == "SKILL.md" else path.stem
        skill_id = metadata.get("id") or metadata.get("name") or fallback
        return SkillRecord(
            id=skill_id,
            name=metadata.get("name") or skill_id,
            description=metadata.get("description", ""),
            version=metadata.get("version", "1.0.0"),
            prompt=body,
            path=str(path.resolve()),
            source=source,
        )

    def discover(self) -> List[SkillRecord]:
        records: Dict[str, SkillRecord] = {}
        for path, source in self._candidates():
            try:
                record = self._parse(path, source)
            except (OSError, UnicodeError):
                continue
            records.setdefault(record.id.casefold(), record)
        return sorted(records.values(), key=lambda item: item.name.casefold())

    def get(self, name: str) -> Optional[SkillRecord]:
        wanted = name.casefold()
        return next(
            (item for item in self.discover() if item.id.casefold() == wanted or item.name.casefold() == wanted),
            None,
        )
