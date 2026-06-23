"""Profile system for NEXUS AI — multi-instance support (inspired by Hermes Agent).

Allows running multiple isolated NEXUS instances, each with its own
config, memory, skills, gateway, and session state.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nexus_path import get_profiles_root, set_active_profile

logger = logging.getLogger(__name__)

PROFILES_FILE = "profiles.json"
PROFILE_CONFIG_FILE = "config.yaml"


def list_profiles() -> List[Dict[str, Any]]:
    """List all available profiles."""
    profiles_root = get_profiles_root()
    if not profiles_root.exists():
        return []

    profiles = []
    for entry in sorted(profiles_root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            meta = _load_profile_meta(entry.name)
            profiles.append({
                "name": entry.name,
                "created": meta.get("created", "unknown"),
                "last_used": meta.get("last_used", "never"),
                "description": meta.get("description", ""),
                "active": os.environ.get("NEXUS_PROFILE") == entry.name,
            })
    return profiles


def create_profile(name: str, description: str = "", clone_from: Optional[str] = None) -> str:
    """Create a new profile.

    If clone_from is provided, copy that profile's config.
    """
    profiles_root = get_profiles_root()
    profile_dir = profiles_root / name

    if profile_dir.exists():
        return f"Profile '{name}' already exists."

    profile_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "name": name,
        "description": description,
        "created": datetime.now().isoformat(),
        "last_used": None,
    }
    _save_profile_meta(name, meta)

    if clone_from:
        source_dir = profiles_root / clone_from
        if source_dir.exists():
            for item in source_dir.iterdir():
                if item.name != PROFILES_FILE:
                    if item.is_file():
                        shutil.copy2(item, profile_dir / item.name)
                    elif item.is_dir():
                        shutil.copytree(item, profile_dir / item.name, dirs_exist_ok=True)
            return f"Profile '{name}' created (cloned from '{clone_from}')."

    return f"Profile '{name}' created."


def switch_profile(name: str) -> str:
    """Switch to a profile. Creates it if it doesn't exist."""
    profiles_root = get_profiles_root()
    profile_dir = profiles_root / name

    if not profile_dir.exists():
        create_profile(name)

    set_active_profile(name)

    meta = _load_profile_meta(name)
    meta["last_used"] = datetime.now().isoformat()
    _save_profile_meta(name, meta)

    return f"Switched to profile '{name}'."


def delete_profile(name: str) -> str:
    """Delete a profile and all its data."""
    profiles_root = get_profiles_root()
    profile_dir = profiles_root / name

    if not profile_dir.exists():
        return f"Profile '{name}' not found."

    active = os.environ.get("NEXUS_PROFILE")
    if active == name:
        return f"Cannot delete active profile '{name}'. Switch to another profile first."

    shutil.rmtree(profile_dir)
    return f"Profile '{name}' deleted."


def _load_profile_meta(name: str) -> Dict[str, Any]:
    profiles_root = get_profiles_root()
    meta_file = profiles_root / name / PROFILES_FILE
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            pass
    return {"name": name, "created": datetime.now().isoformat(), "last_used": None, "description": ""}


def _save_profile_meta(name: str, meta: Dict[str, Any]):
    profiles_root = get_profiles_root()
    meta_file = profiles_root / name / PROFILES_FILE
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    meta_file.write_text(json.dumps(meta, indent=2))


def get_profile_path(name: str) -> Optional[Path]:
    """Get the filesystem path for a profile."""
    profile_dir = get_profiles_root() / name
    if profile_dir.exists():
        return profile_dir
    return None
