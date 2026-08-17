"""Security tests: path traversal / workspace escape in NEXUS file tools.

Every file tool must reject paths that resolve outside its configured
``root_dir``, including the classic ``..`` sibling-dir escape and an absolute
path escape. These tests prove the fix that replaced unsafe ``str.startswith``
prefix checks with ``os.path.commonpath`` containment, and the addition of a
containment guard to code_search/shortcuts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions.tools.built_in.reading.scripts.reading import ReadingTool
from extensions.tools.built_in.deleting.scripts.deleting import DeletingTool
from extensions.tools.built_in.creating.scripts.creating import CreatingTool
from extensions.tools.built_in.modifying.scripts.modifying import ModifyingTool
from extensions.tools.built_in.code_search.scripts.code_search import CodeSearchTool
from extensions.tools.built_in.shortcuts.scripts.shortcuts import ShortcutsTool


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixture: a workspace plus a SIBLING directory whose name has the workspace
# path as a string prefix. The old ``startswith`` checks would treat paths
# inside the sibling as "inside the workspace"; commonpath does not.
# ---------------------------------------------------------------------------

def _workspace_env(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sibling = tmp_path / "ws_evil"  # same string prefix as the workspace root
    sibling.mkdir(exist_ok=True)
    return ws, sibling


# ---------------------------------------------------------------------------
# Reading tool
# ---------------------------------------------------------------------------

class TestReadingToolPathTraversal:
    def test_reading_blocks_prefix_sibling_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        (ws / "ok.txt").write_text("inside", encoding="utf-8")
        (sibling / "secret.txt").write_text("TOP_SECRET", encoding="utf-8")

        result = _run(ReadingTool(root_dir=str(ws)).execute(
            path=os.path.join("..", "ws_evil", "secret.txt")))
        assert result.success is False
        assert "Path traversal blocked" in result.error

    def test_reading_blocks_absolute_path_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        outside = tmp_path / "outside_secret.txt"
        outside.write_text("TOP_SECRET", encoding="utf-8")

        result = _run(ReadingTool(root_dir=str(ws)).execute(path=str(outside)))
        assert result.success is False
        assert "Path traversal blocked" in result.error

    def test_reading_still_reads_inside_workspace(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "doc.md").write_text("hello world", encoding="utf-8")
        result = _run(ReadingTool(root_dir=str(ws)).execute(path="doc.md"))
        assert result.success is True
        assert "hello world" in result.output

    def test_reading_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "doc.txt").write_text("hello world", encoding="utf-8")
        tool = ReadingTool(root_dir=str(ws))
        original = tool._execute_sync

        def slow_read(*args, **kwargs):
            import time

            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(tool, "_execute_sync", slow_read)

        async def run_with_heartbeat():
            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                result = await tool.execute(path="doc.txt")
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            return result, ticks

        result, ticks = _run(run_with_heartbeat())
        assert result.success is True
        assert ticks >= 4


# ---------------------------------------------------------------------------
# Deleting tool
# ---------------------------------------------------------------------------

class TestDeletingToolPathTraversal:
    def test_deleting_blocks_prefix_sibling_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        (sibling / "victim.txt").write_text("do not delete", encoding="utf-8")

        result = _run(DeletingTool(root_dir=str(ws)).execute(
            path=os.path.join("..", "ws_evil", "victim.txt")))
        assert result.success is False
        assert "Path traversal blocked" in result.error
        # The victim file must still exist.
        assert (sibling / "victim.txt").exists()

    def test_deleting_still_deletes_inside_workspace(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "old.txt").write_text("x", encoding="utf-8")
        result = _run(DeletingTool(root_dir=str(ws)).execute(path="old.txt"))
        assert result.success is True
        assert not (ws / "old.txt").exists()


# ---------------------------------------------------------------------------
# Creating tool (regression: must keep blocking while allowing legit files)
# ---------------------------------------------------------------------------

class TestCreatingToolPathTraversal:
    def test_creating_blocks_prefix_sibling_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)

        result = _run(CreatingTool(root_dir=str(ws)).execute(
            path=os.path.join("..", "ws_evil", "planted.txt"), content="evil"))
        assert result.success is False
        assert "Path traversal blocked" in result.error
        assert not (sibling / "planted.txt").exists()

    def test_creating_still_creates_inside_workspace(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        result = _run(CreatingTool(root_dir=str(ws)).execute(path="new.txt", content="hi"))
        assert result.success is True
        assert (ws / "new.txt").read_text(encoding="utf-8") == "hi"


# ---------------------------------------------------------------------------
# Modifying tool (regression)
# ---------------------------------------------------------------------------

class TestModifyingToolPathTraversal:
    def test_modifying_blocks_prefix_sibling_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        (sibling / "conf.txt").write_text("original", encoding="utf-8")

        result = _run(ModifyingTool(root_dir=str(ws)).execute(
            path=os.path.join("..", "ws_evil", "conf.txt"),
            old_string="original",
            new_string="PWNED",
        ))
        assert result.success is False
        assert "Path traversal blocked" in result.error
        assert (sibling / "conf.txt").read_text(encoding="utf-8") == "original"

    def test_modifying_still_edits_inside_workspace(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "conf.txt").write_text("original", encoding="utf-8")
        result = _run(ModifyingTool(root_dir=str(ws)).execute(
            path="conf.txt", old_string="original", new_string="edited"))
        assert result.success is True
        assert (ws / "conf.txt").read_text(encoding="utf-8") == "edited"

    def test_modifying_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "conf.txt").write_text("original", encoding="utf-8")
        tool = ModifyingTool(root_dir=str(ws))
        original = tool._execute_sync

        def slow_modify(*args, **kwargs):
            import time

            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(tool, "_execute_sync", slow_modify)

        async def run_with_heartbeat():
            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                result = await tool.execute(
                    path="conf.txt", old_string="original", new_string="edited"
                )
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            return result, ticks

        result, ticks = _run(run_with_heartbeat())
        assert result.success is True
        assert ticks >= 4


# ---------------------------------------------------------------------------
# Code search tool: ``path`` parameter must not escape the workspace
# ---------------------------------------------------------------------------

class TestCodeSearchPathContainment:
    def _setup(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "src").mkdir(exist_ok=True)
        (ws / "src" / "hello.py").write_text("print('GREP_NEEDLE')", encoding="utf-8")
        (tmp_path / "outside_leak.txt").write_text("GREP_NEEDLE", encoding="utf-8")
        return ws

    def test_code_search_blocks_parent_path_escape(self, tmp_path):
        ws = self._setup(tmp_path)

        result = _run(CodeSearchTool(root_dir=str(ws)).execute(
            pattern="GREP_NEEDLE", path="..", mode="grep"))
        assert result.success is False
        assert "outside the workspace" in result.error

    def test_code_search_blocks_absolute_path_escape(self, tmp_path):
        ws = self._setup(tmp_path)

        result = _run(CodeSearchTool(root_dir=str(ws)).execute(
            pattern="GREP_NEEDLE", path=str(tmp_path), mode="glob"))
        assert result.success is False
        assert "outside the workspace" in result.error

    def test_code_search_still_searches_workspace(self, tmp_path):
        ws = self._setup(tmp_path)

        result = _run(CodeSearchTool(root_dir=str(ws)).execute(
            pattern="GREP_NEEDLE", path="src", mode="grep"))
        assert result.success is True
        assert "hello.py" in result.output
        assert "outside_leak" not in result.output

    def test_code_search_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ws = self._setup(tmp_path)
        tool = CodeSearchTool(root_dir=str(ws))
        original = tool._execute_sync

        def slow_search(*args, **kwargs):
            import time

            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(tool, "_execute_sync", slow_search)

        async def run_with_heartbeat():
            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                result = await tool.execute("GREP_NEEDLE", path="src", mode="grep")
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            return result, ticks

        result, ticks = _run(run_with_heartbeat())
        assert result.success is True
        assert ticks >= 4


# ---------------------------------------------------------------------------
# Shortcuts tool: target path must stay inside the workspace
# ---------------------------------------------------------------------------

class TestShortcutsPathContainment:
    def test_shortcuts_blocks_parent_path_escape(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        (sibling / "hidden.txt").write_text("secret", encoding="utf-8")

        result = _run(ShortcutsTool(root_dir=str(ws)).execute(
            action="list", path=os.path.join("..", "ws_evil")))
        assert result.success is False
        assert "Path traversal blocked" in result.error

    def test_shortcuts_blocks_absolute_path_listing(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)

        result = _run(ShortcutsTool(root_dir=str(ws)).execute(
            action="list", path=str(tmp_path)))
        assert result.success is False
        assert "Path traversal blocked" in result.error

    def test_shortcuts_still_lists_workspace(self, tmp_path):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "sub").mkdir(exist_ok=True)
        (ws / "sub" / "a.txt").write_text("a", encoding="utf-8")

        result = _run(ShortcutsTool(root_dir=str(ws)).execute(action="list", path="sub"))
        assert result.success is True
        assert "a.txt" in result.output

    def test_shortcuts_blocks_symlink_target_outside_workspace(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        secret = sibling / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        link = ws / "linked-secret"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        result = _run(ShortcutsTool(root_dir=str(ws)).execute(action="info", path="linked-secret"))
        assert result.success is False
        assert "Path traversal blocked" in result.error

    def test_shortcuts_tree_does_not_follow_child_symlink(self, tmp_path):
        ws, sibling = _workspace_env(tmp_path)
        outside_dir = sibling / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")
        link = ws / "linked-dir"
        try:
            link.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"directory symlink creation unavailable: {exc}")

        result = _run(ShortcutsTool(root_dir=str(ws)).execute(action="tree"))
        assert result.success is True
        assert "linked-dir@" in result.output
        assert "secret.txt" not in result.output

    def test_shortcuts_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ws, _sibling = _workspace_env(tmp_path)
        (ws / "sub").mkdir(exist_ok=True)
        (ws / "sub" / "a.txt").write_text("a", encoding="utf-8")
        tool = ShortcutsTool(root_dir=str(ws))
        original = tool._execute_sync

        def slow_operation(*args, **kwargs):
            import time

            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(tool, "_execute_sync", slow_operation)

        async def run_with_heartbeat():
            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                result = await tool.execute(action="list", path="sub")
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            return result, ticks

        result, ticks = _run(run_with_heartbeat())
        assert result.success is True
        assert ticks >= 4
