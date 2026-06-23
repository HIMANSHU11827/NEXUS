"""Centralized version management for all NEXUS modules."""

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class VersionManager:
    """Manages version tracking, bumping, and compatibility for all NEXUS modules."""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or os.getcwd())
        self._versions: Dict[str, str] = {}
        self._scan()

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
                pass

    def get_version(self, name: str) -> Optional[str]:
        return self._versions.get(name)

    def list_versions(self) -> Dict[str, str]:
        return dict(self._versions)

    def bump(self, name: str, part: str = "patch", root: Optional[str] = None) -> Optional[str]:
        """Bump version for a module. part = major|minor|patch"""
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
                pass
        return None

    def _bump_str(self, version: str, part: str) -> str:
        parts = version.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
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
