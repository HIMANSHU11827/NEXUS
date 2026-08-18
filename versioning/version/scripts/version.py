"""Centralized version management for all NEXUS modules.

Two version systems exist in the codebase: ``evolution/version`` (this one,
scans ``*.jsnol`` manifests) and ``lifecycle/version`` (X.Y helpers for
lifecycle entities, owned by a companion agent â€” never edited here). The
versioning *within evolution/* is unified on this manager: every forge obtains
its version exclusively through ``VersionManager.ensure`` (create) or
``VersionManager.bump`` (refine) â€” there is no per-forge local bumping.

To keep forge wiring intact without touching every caller, this manager gains
a JSON-backed registry fallback: entity names that don't match a ``.jsnol``
manifest (tools, skills, plugins, knowledge, memory, ...) get a monotonic
per-name version persisted under ``<root>/.nexus/versions.json`` so forges
receive real version strings instead of ``None``.
"""

from __future__ import annotations

__version__ = "2.0.0"
import json
import logging
import os

logger = logging.getLogger("versioning.version")
from pathlib import Path
from typing import Dict, Optional, Tuple


class VersionManager:
    """Manages version tracking, bumping, and compatibility for all NEXUS modules."""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or os.getcwd())
        self._versions: Dict[str, str] = {}
        self._fallback_versions: Dict[str, str] = {}
        self._load_registry()
        self._scan()

    def _registry_path(self) -> Path:
        """Where the JSON fallback registry lives for this manager root."""
        return self.root / ".nexus" / "versions.json"

    def _load_registry(self):
        """Load previously persisted fallback versions (best-effort)."""
        self._fallback_versions = {}
        try:
            path = self._registry_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._fallback_versions = {
                        str(k): str(v) for k, v in data.items()
                    }
        except Exception:
            logger.warning("evolution/version/scripts/version.py: _load_registry: suppressed error", exc_info=True)

    def _save_registry(self):
        """Persist fallback versions (best-effort, no-op on write failure)."""
        try:
            path = self._registry_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._fallback_versions, f, indent=2, sort_keys=True)
        except Exception:
            logger.warning("evolution/version/scripts/version.py: _save_registry: suppressed error", exc_info=True)

    def _scan(self):
        """Scan all .jsnol files to collect current versions."""
        self._versions.clear()
        for jsnol_path in self.root.rglob("*.jsnol"):
            try:
                with open(jsnol_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name", jsnol_path.stem)
                ver = data.get("version", "0.0.0")
                self._versions[name] = ver
            except Exception:
                logger.warning("evolution/version/scripts/version.py:30 _scan: suppressed error", exc_info=True)
                pass
        # Merge persisted fallback versions so arbitrary forge names survive
        # restarts. Real .jsnol manifests take precedence when both exist.
        for name, ver in self._fallback_versions.items():
            self._versions.setdefault(name, ver)

    def get_version(self, name: str) -> Optional[str]:
        return self._versions.get(name)

    def list_versions(self) -> Dict[str, str]:
        return dict(self._versions)

    def ensure(self, name: str, version: str = "1.0.0",
               root: Optional[str] = None) -> str:
        """Guarantee a real version string exists for ``name``.

        Returns the existing version when the entity is already tracked (a
        ``.jsnol`` manifest or the JSON registry), otherwise records ``version``
        as the initial version in the registry and returns it. Never returns
        ``None`` â€” forges use this as the single version source for created
        artifacts.
        """
        existing = self.get_version(name)
        if existing:
            return existing
        search_root = Path(root or self.root)
        for jsnol_path in search_root.rglob("*.jsnol"):
            try:
                with open(jsnol_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("name") == name or jsnol_path.stem == name:
                    ver = str(data.get("version", version))
                    self._versions[name] = ver
                    return ver
            except Exception:
                logger.warning("evolution/version/scripts/version.py: ensure: suppressed error", exc_info=True)
                pass
        self._fallback_versions[name] = version
        self._versions[name] = version
        self._save_registry()
        return version

    def bump(self, name: str, part: str = "patch", root: Optional[str] = None,
             current: Optional[str] = None) -> Optional[str]:
        """Bump version for a module. part = major|minor|patch

        First matches a ``*.jsnol`` manifest by name exactly as before. If no
        manifest matches (forge-created tools/skills/plugins/etc.), falls back
        to a monotonic per-name version in the JSON registry at
        ``<self.root>/.nexus/versions.json``.

        ``current`` is an optional seed: when the name is not yet tracked in the
        registry, it becomes the baseline so a pre-existing on-disk version is
        respected instead of silently resetting to a default. Every forge calls
        this one function (or ``ensure``) for its versioning â€” no per-forge
        local bumping.
        """
        search_root = Path(root or self.root)
        for jsnol_path in search_root.rglob("*.jsnol"):
            try:
                with open(jsnol_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("name") == name or jsnol_path.stem == name:
                    current = data.get("version", "0.0.0")
                    new_ver = self._bump_str(current, part)
                    data["version"] = new_ver
                    with open(jsnol_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    self._versions[name] = new_ver
                    return new_ver
            except Exception:
                logger.warning("evolution/version/scripts/version.py:54 bump: suppressed error", exc_info=True)
                pass

        # Fallback: no .jsnol manifest matched â€” track arbitrary entity names
        # in a JSON registry so forges actually get bumps instead of None.
        tracked = self._fallback_versions.get(name)
        if tracked is None and current is not None:
            tracked = str(current)
            self._fallback_versions[name] = tracked
        baseline = tracked or current or "1.0.0"
        new_ver = self._bump_str(str(baseline), part)
        self._fallback_versions[name] = new_ver
        self._versions[name] = new_ver
        self._save_registry()
        return new_ver

    def _bump_str(self, version: str, part: str) -> str:
        parts = version.split(".")
        while len(parts) < 3:
            parts.append("0")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        if part == "major":
            major += 1; minor = 0; patch = 0
        elif part == "minor":
            minor += 1; patch = 0
        else:
            patch += 1
        return f"{major}.{minor}.{patch}"

    def check_compatibility(self, name: str, required: str) -> Tuple[bool, str]:
        """Check if installed version satisfies required version (same major)."""
        current = self.get_version(name)
        if not current:
            return False, f"{name}: not found"
        cur_major = int(current.split(".")[0])
        req_major = int(required.split(".")[0])
        if cur_major == req_major:
            return True, f"{name} {current} compatible with {required}"
        return False, f"{name} {current} INCOMPATIBLE with {required} (major mismatch)"

    def get_all_versions_report(self) -> str:
        lines = [f"{k}: {v}" for k, v in sorted(self._versions.items())]
        return "\n".join(lines) if lines else "No versions found"
