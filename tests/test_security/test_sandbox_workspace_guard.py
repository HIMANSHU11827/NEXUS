"""Security tests: sandbox workspace-only guard must not be bypassed by env vars.

The NORMAL/DOCKER sandbox tier claims "workspace-only" isolation. Commands that
smuggle an outside path through an environment variable (``$VAR`` / ``%VAR%``)
must be blocked, not just literal path arguments.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.sandbox_manager import SovereignSandbox


class TestSandboxWorkspaceGuard:
    def test_literal_outside_path_is_blocked(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside_secret.txt"
        outside.write_text("TOP_SECRET", encoding="utf-8")

        sandbox = SovereignSandbox(str(ws))
        if os.name == "nt":
            cmd = f"type \"{outside}\""
        else:
            cmd = f"cat {outside}"
        block = sandbox._validate_workspace_scope(cmd, str(ws))
        assert block is not None
        assert "[SANDBOX_BLOCK]" in block

    def test_env_var_smuggled_path_is_blocked(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside_secret.txt"
        outside.write_text("TOP_SECRET", encoding="utf-8")
        monkeypatch.setenv("SECRET_DIR_XYZZY", str(tmp_path))

        sandbox = SovereignSandbox(str(ws))
        if os.name == "nt":
            cmd = r"type %SECRET_DIR_XYZZY%\outside_secret.txt"
        else:
            cmd = "cat $SECRET_DIR_XYZZY/outside_secret.txt"
        block = sandbox._validate_workspace_scope(cmd, str(ws))
        assert block is not None
        assert "[SANDBOX_BLOCK]" in block

    def test_dollar_braced_var_smuggled_path_is_blocked(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside_secret.txt"
        outside.write_text("TOP_SECRET", encoding="utf-8")
        monkeypatch.setenv("OUTSIDE_HOME_XYZZY", str(tmp_path))

        sandbox = SovereignSandbox(str(ws))
        cmd = "cat ${OUTSIDE_HOME_XYZZY}/outside_secret.txt"
        block = sandbox._validate_workspace_scope(cmd, str(ws))
        assert block is not None
        assert "[SANDBOX_BLOCK]" in block

    def test_inside_relative_path_is_allowed(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "data.txt").write_text("x", encoding="utf-8")

        sandbox = SovereignSandbox(str(ws))
        if os.name == "nt":
            cmd = f"type \"{ws / 'data.txt'}\""
        else:
            cmd = f"cat {ws / 'data.txt'}"
        assert sandbox._validate_workspace_scope(cmd, str(ws)) is None

    def test_workdir_outside_workspace_is_blocked(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside_dir = tmp_path / "elsewhere"
        outside_dir.mkdir()

        sandbox = SovereignSandbox(str(ws))
        block = sandbox._validate_workspace_scope("dir", str(outside_dir))
        assert block is not None
        assert "[SANDBOX_BLOCK]" in block
