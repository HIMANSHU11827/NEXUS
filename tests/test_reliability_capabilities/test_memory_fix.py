"""Capabilities hardening: memory forge failure path.

``sync_all`` must never raise when the evolution memory forge fails, must log
a warning naming the forge function, and must still persist the session.
"""

import asyncio
import logging
from pathlib import Path

from memory import MemoryManager


def test_sync_all_forge_failure_is_suppressed_and_logged(tmp_path, monkeypatch, caplog):
    class FailingForge:
        def __init__(self, root_dir):
            self.root_dir = root_dir

        def forge(self, *args, **kwargs):
            raise RuntimeError("forge exploded")

    monkeypatch.setattr("evolution.memory_forge.scripts.forge.MemoryForge", FailingForge)
    mm = MemoryManager(str(tmp_path), session_id="forge_fail")
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.memory"):
            asyncio.run(mm.sync_all(
                "user message",
                "assistant response",
                verified_actions=[{"verified": True, "success": True, "tool": "web_search"}],
                tool_results=[
                    {"tool": "web_search", "verified": True, "output": "found it", "call_id": "c1"}
                ],
            ))
    finally:
        mm.shutdown()

    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert any("MemoryForge.forge" in record.getMessage() for record in warnings), (
        "forge failure must be logged with the forge function name"
    )
    session_path = tmp_path / "logs" / "sessions" / "forge_fail.json"
    assert session_path.is_file(), "session persistence must continue despite forge failure"


def test_sync_all_without_verified_evidence_skips_forge(tmp_path, monkeypatch, caplog):
    class QuietForge:
        def __init__(self, root_dir):
            self.root_dir = root_dir

        def forge(self, *args, **kwargs):
            raise AssertionError("forge must not be called without verified evidence")

    monkeypatch.setattr("evolution.memory_forge.scripts.forge.MemoryForge", QuietForge)
    mm = MemoryManager(str(tmp_path), session_id="forge_skip")
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.memory"):
            asyncio.run(mm.sync_all("user message", "assistant response"))
    finally:
        mm.shutdown()

    assert not any(
        "MemoryForge" in record.getMessage() for record in caplog.records
    ), "unverified sessions must not attempt the forge"