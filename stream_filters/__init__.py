"""Filter internal orchestration noise from user-facing chat streams."""

from __future__ import annotations

import re

_HIVE_BLACKBOARD = re.compile(
    r"^\[(?:ENGINEER|AUDITOR|ARCHITECT|RESEARCHER|LIBRARIAN|SYSTEM|CODER|REVIEWER|QA_EXPERT)\s+@\s+MISSION_",
    re.IGNORECASE,
)

_INTERNAL_PREFIXES = (
    "[NEXUS_BOOT]:",
    "[THINKING:",
    "[HIVE:",
    "[HIVE_STATUS]:",
    "[SYSTEM: COMPLEX MISSION",
    "[AUTO_OBSERVATION]:",
)


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text or "")


def is_internal_stream_line(text: str) -> bool:
    """True when a streamed line should not appear in chat UIs."""
    line = strip_ansi(text).strip()
    if not line:
        return False
    if _HIVE_BLACKBOARD.match(line):
        return True
    if "@ MISSION_" in line and "RESULT TASK-" in line:
        return True
    if any(line.startswith(prefix) for prefix in _INTERNAL_PREFIXES):
        return True
    if re.match(r"^\[HIVE:\s*\d+\s+nodes updated\]", line, re.IGNORECASE):
        return True
    return False


def filter_stream_text(text: str) -> str:
    """Remove internal lines from a multi-line stream chunk."""
    if not text:
        return ""
    kept = []
    for line in text.splitlines():
        if is_internal_stream_line(line):
            continue
        kept.append(line)
    return "\n".join(kept)
