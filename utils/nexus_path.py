"""NEXUS path and profile resolution utilities."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("nexus.path")


def get_nexus_home() -> Path:
    nexus_home = os.environ.get("NEXUS_HOME")
    if nexus_home:
        return Path(nexus_home).resolve()
    return Path.home() / ".nexus"


def get_nexus_base_home() -> Path:
    base_home = os.environ.get("NEXUS_BASE_HOME")
    if base_home:
        return Path(base_home).resolve()
    return get_nexus_home()


def get_profiles_root() -> Path:
    return get_nexus_base_home() / "profiles"


def get_active_profile() -> str | None:
    return os.environ.get("NEXUS_PROFILE")


def set_active_profile(name: str) -> None:
    base_home = get_nexus_base_home()
    os.environ["NEXUS_PROFILE"] = name
    os.environ["NEXUS_BASE_HOME"] = str(base_home)
    os.environ["NEXUS_HOME"] = str(base_home / "profiles" / name)


def display_nexus_home() -> str:
    home = get_nexus_home()
    try:
        user_home = Path.home()
        if home.is_relative_to(user_home):
            return (Path("~") / home.relative_to(user_home)).as_posix()
    except Exception:
        logger.warning("utils/nexus_path.py:35 display_nexus_home: suppressed error", exc_info=True)
        pass
    return home.as_posix()


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
