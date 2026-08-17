"""Shared atomic session persistence primitives.

The GUI, V5 loop, and MemoryManager can all write the same session transcript.
Keeping the lock and replacement protocol here prevents each layer from
silently inventing a different durability boundary.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Iterator


_SESSION_WRITE_LOCK = threading.RLock()


@contextmanager
def session_interprocess_lock(path: str) -> Iterator[None]:
    """Serialize one session path across processes with a SQLite mutex."""
    lock_path = f"{path}.lock.sqlite"
    connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS session_mutex "
            "(id INTEGER PRIMARY KEY CHECK (id = 1))"
        )
        connection.execute("INSERT OR IGNORE INTO session_mutex(id) VALUES (1)")
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


@contextmanager
def session_write_lock(path: str) -> Iterator[None]:
    """Serialize session read/merge/write work within and across processes."""
    with _SESSION_WRITE_LOCK:
        with session_interprocess_lock(path):
            yield


def atomic_write_json(path: str, value: Any) -> None:
    """Fsync and atomically replace one JSON file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


__all__ = ["atomic_write_json", "session_interprocess_lock", "session_write_lock"]
