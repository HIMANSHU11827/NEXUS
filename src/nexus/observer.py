"""Headless, replay-safe follower for persisted canonical work events."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import TextIO

from nexus.runtime import safe_session_id


def _safe_session_id(value: str) -> str:
    return safe_session_id(value)


def event_path(project_root: str, session_id: str) -> Path:
    return Path(project_root) / ".nexus" / "workspace" / "work_events" / f"{_safe_session_id(session_id)}.jsonl"


def _read_new(path: Path, offset: int, after_sequence: int) -> tuple[int, int, list[dict]]:
    if not path.exists():
        return 0, after_sequence, []
    size = path.stat().st_size
    if size < offset:
        offset = 0
    events: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line:
                break
            line_end = handle.tell()
            # A writer can be between write() calls, leaving a valid JSON
            # record without its terminating newline. Keep the offset at the
            # start of that record so the next poll retries it intact.
            if not line.endswith("\n"):
                break
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                offset = line_end
                continue
            offset = line_end
            if not isinstance(event, dict):
                continue
            try:
                sequence = int(event.get("sequence") or 0)
            except (TypeError, ValueError):
                continue
            if sequence <= after_sequence or str(event.get("visibility") or "public").lower() == "internal":
                continue
            events.append(event)
            after_sequence = max(after_sequence, sequence)
    return offset, after_sequence, events


def follow_events(
    project_root: str,
    session_id: str = "default",
    *,
    after_sequence: int = 0,
    follow: bool = True,
    poll_seconds: float = 0.25,
):
    """Yield public append-only events, including events written after startup."""
    path = event_path(project_root, session_id)
    offset = 0
    cursor = max(0, int(after_sequence))
    while True:
        offset, cursor, events = _read_new(path, offset, cursor)
        yield from events
        if not follow:
            return
        time.sleep(max(0.05, poll_seconds))


def _format_text(event: dict) -> str:
    event_type = event.get("event_type") or event.get("type") or "event"
    status = event.get("status") or ""
    title = event.get("title") or event.get("action") or ""
    target = event.get("target") or event.get("path") or ""
    suffix = f" {target}" if target else ""
    return f"[{event.get('sequence', '?')}] {event_type} {status}: {title}{suffix}".rstrip()


def run_observer(
    project_root: str,
    session_id: str,
    *,
    after_sequence: int = 0,
    output: TextIO,
    format: str = "json",
    follow: bool = True,
) -> int:
    for event in follow_events(project_root, session_id, after_sequence=after_sequence, follow=follow):
        if format == "text":
            output.write(_format_text(event) + "\n")
        else:
            output.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        output.flush()
    return 0


def observer_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--observe", nargs="?", const="default", metavar="SESSION", help="Stream public canonical events for a session without starting GUI/TUI")
    parser.add_argument("--after-sequence", type=int, default=0, help="Resume observation after this persisted event sequence")
    parser.add_argument("--observe-format", choices=("json", "text"), default="json", help="Observer output format (default: json)")
    parser.add_argument("--observe-once", action="store_true", help="Replay currently persisted events and exit")
