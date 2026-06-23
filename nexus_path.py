"""NEXUS path and profile resolution utilities."""

from __future__ import annotations

import os
from pathlib import Path


def get_nexus_home() -> Path:
    nexus_home = os.environ.get("NEXUS_HOME")
    if nexus_home:
        return Path(nexus_home).resolve()
    return Path.home() / ".nexus"


def get_profiles_root() -> Path:
    return get_nexus_home() / "profiles"


def get_active_profile() -> str | None:
    return os.environ.get("NEXUS_PROFILE")


def set_active_profile(name: str) -> None:
    os.environ["NEXUS_PROFILE"] = name
    os.environ["NEXUS_HOME"] = str(get_nexus_home() / name)


def display_nexus_home() -> str:
    home = get_nexus_home()
    try:
        user_home = Path.home()
        if home.is_relative_to(user_home):
            return (Path("~") / home.relative_to(user_home)).as_posix()
    except Exception:
        pass
    return home.as_posix()


_ROOT = os.path.dirname(os.path.abspath(__file__))
