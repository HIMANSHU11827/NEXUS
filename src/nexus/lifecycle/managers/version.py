"""Shared versioning system for NEXUS lifecycle entities.

Every skill, tool, plugin, cron job, improvement cycle, and memory record
gets an auto-incrementing version:

- Default: "1.0"
- Minor improvement: 1.0 → 1.1 → 1.2 → ... (bump_minor)
- Major upgrade: 1.9 → 2.0 → 2.1 → ... (bump_major)
"""

import re
from typing import Tuple


def default_version() -> str:
    return "1.0"


def parse_version(version: str) -> Tuple[int, int]:
    """Parse 'X.Y' into (major, minor). Returns (1, 0) on failure."""
    match = re.match(r"^(\d+)\.(\d+)$", version)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1, 0


def bump_minor(version: str) -> str:
    """Increment minor: 1.0 → 1.1, 2.5 → 2.6"""
    major, minor = parse_version(version)
    return f"{major}.{minor + 1}"


def bump_major(version: str) -> str:
    """Increment major, reset minor: 1.9 → 2.0, 2.5 → 3.0"""
    major, _ = parse_version(version)
    return f"{major + 1}.0"


def improve_version(current: str, is_major: bool = False) -> str:
    """Improve a version. Default is minor bump. Pass is_major=True for major bump."""
    if is_major:
        return bump_major(current)
    return bump_minor(current)


def format_version_list(versions: list) -> str:
    """Format version history for display: 1.0 → 1.1 → 1.2"""
    return " → ".join(versions) if versions else "1.0"
