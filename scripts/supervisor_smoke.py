"""Smoke-test the outer supervisor lock without pytest temp fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from nexus.supervisor import NexusSupervisor


def main() -> int:
    root = Path.cwd()
    lock_path = root / ".nexus" / "supervisor-smoke.lock"
    lock_path.unlink(missing_ok=True)
    first = NexusSupervisor(str(root), lock_path=str(lock_path))
    second = NexusSupervisor(str(root), lock_path=str(lock_path))
    if not first._acquire_lock():
        raise SystemExit("first supervisor could not acquire smoke lock")
    try:
        if second._acquire_lock():
            raise SystemExit("duplicate supervisor unexpectedly acquired lock")
    finally:
        first._release_lock()

    lock_path.write_text(json.dumps({"pid": 999999, "started_at": 0}), encoding="utf-8")
    try:
        if not second._acquire_lock():
            raise SystemExit("stale supervisor lock was not reclaimed")
    finally:
        second._release_lock()
        lock_path.unlink(missing_ok=True)
    print("SUPERVISOR_LOCK_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
