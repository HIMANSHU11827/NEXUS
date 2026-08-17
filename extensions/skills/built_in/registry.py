"""Canonical, side-effect-free NEXUS skill discovery.

``.opencode/skills/<name>/SKILL.md`` is the canonical format.  Legacy
``skills/<name>/SKILL.md`` and ``skills/<name>.md`` files remain readable, but a
canonical skill with the same id always wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in minimal installs
    yaml = None


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
        legacy = self.root / "extensions" / "skills" / "built_in"
        # Canonical built-in skills location after the restructure:
        # <root>/extensions/skills/built_in/. This is scanned only when ``root``
        # is the NEXUS project, so an isolated tmp-project SkillRegistry (used by
        # tests) does not accidentally pull in the project's shipped skills.
        bundled = self.root / "extensions" / "skills" / "built_in"
        for base, source in ((canonical, "opencode"), (legacy, "legacy"), (bundled, "bundled")):
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.name not in {"README.md", "read.md"} and (
                    path.name == "SKILL.md" or (path.parent == base and path.suffix.lower() == ".md")
                ):
                    yield path, source

    @staticmethod
    def _fallback_frontmatter(text: str) -> Dict[str, Any]:
        """Parse top-level scalar YAML fields without consuming nested keys.

        PyYAML is part of the normal NEXUS installation. This conservative
        fallback preserves legacy minimal environments and, unlike the old
        parser, cannot let an indented credential ``description`` overwrite
        the skill's top-level description.
        """
        metadata: Dict[str, Any] = {}
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line or line[0].isspace() or ":" not in line:
                index += 1
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if value in {"|", ">"}:
                folded = value == ">"
                block: List[str] = []
                index += 1
                while index < len(lines):
                    continuation = lines[index]
                    if continuation and not continuation[0].isspace():
                        break
                    block.append(continuation.strip())
                    index += 1
                metadata[key] = (" " if folded else "\n").join(block).strip()
                continue
            metadata[key] = value.strip('"\'')
            index += 1
        return metadata

    @staticmethod
    def _parse(path: Path, source: str) -> SkillRecord:
        content = path.read_text(encoding="utf-8")
        metadata: Dict[str, Any] = {}
        body = content.strip()
        match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", content, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            if yaml is not None:
                try:
                    loaded = yaml.safe_load(frontmatter) or {}
                except Exception:
                    loaded = {}
                if isinstance(loaded, dict):
                    metadata = {str(key).strip().lower(): value for key, value in loaded.items()}
            if not metadata:
                metadata = SkillRegistry._fallback_frontmatter(frontmatter)
            body = match.group(2).strip()
        fallback = path.parent.name if path.name == "SKILL.md" else path.stem
        skill_id = str(metadata.get("id") or metadata.get("name") or fallback).strip()
        name = str(metadata.get("name") or skill_id).strip()
        description = str(metadata.get("description") or "").strip()
        version = str(metadata.get("version") or "1.0.0").strip()
        return SkillRecord(
            id=skill_id,
            name=name,
            description=description,
            version=version,
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
