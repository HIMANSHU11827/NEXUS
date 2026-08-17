import json
import sys

import pytest


def test_setup_complete_marker_disables_first_run(tmp_path):
    import nexus

    config_dir = tmp_path / "configure"
    config_dir.mkdir()
    (config_dir / ".env").write_text("TELEGRAM_BOT_TOKEN=your_token_here\n", encoding="utf-8")

    assert nexus._check_first_run(str(tmp_path)) is True

    nexus._mark_setup_complete(str(tmp_path), "setup")

    assert nexus._check_first_run(str(tmp_path)) is False
    assert not (config_dir / ".first_run").exists()
    data = json.loads((config_dir / ".setup_complete").read_text(encoding="utf-8"))
    assert data["mode"] == "setup"


def test_quick_configure_writes_complete_marker(tmp_path):
    import nexus

    nexus._quick_configure(str(tmp_path))

    assert nexus._check_first_run(str(tmp_path)) is False
    assert (tmp_path / "configure" / ".env").exists()
    assert (tmp_path / "configure" / "provider.yml").exists()
    assert (tmp_path / "configure" / "settings.yml").exists()
    settings = (tmp_path / "configure" / "settings.yml").read_text(encoding="utf-8")
    assert "default_provider:" not in settings
    assert "provider_name:" not in settings


def test_setup_alias_inserts_setup_arg(monkeypatch):
    import nexus
    import tui.setup_wizard as setup_wizard

    monkeypatch.setattr(sys, "argv", ["nexus-configure"])
    monkeypatch.setattr(nexus, "_setup_environment", lambda: "C:/tmp/nexus-test")
    monkeypatch.setattr(nexus, "_mark_setup_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup_wizard, "run", lambda root: setattr(nexus, "_alias_test_root", root))

    nexus.boot()

    assert getattr(nexus, "_alias_test_root") == "C:/tmp/nexus-test"


@pytest.mark.parametrize(
    ("command", "flag"),
    [
        ("nexus-tui", "--tui"),
        ("nexus-shell", "--shell"),
        ("nexus-gui", "--gui"),
        ("nexus-server", "--server"),
        ("nexus-api", "--server"),
        ("nexus-gateway", "--gateway"),
        ("nexus-setup", "--setup"),
        ("nexus-configure", "--setup"),
        ("nexus-config", "--setup"),
        ("nexus-settings", "--setup"),
        ("nexus-quick", "--quick"),
        ("nexus-reset", "--reset"),
        ("nexus-export", "--export"),
        ("nexus-export-full", "--export-full"),
        ("nexus-import", "--import"),
        ("nexus-import-full", "--import-full"),
        ("nexus-version", "--version"),
        ("nexus-help", "--help"),
    ],
)
def test_command_aliases_inject_expected_flags(command, flag):
    import nexus

    assert nexus._apply_command_alias([command, "arg1"]) == [command, flag, "arg1"]


def test_plain_nexus_does_not_inject_setup():
    import nexus

    assert nexus._apply_command_alias(["nexus"]) == ["nexus"]
    assert nexus._apply_command_alias(["nexus", "--server"]) == ["nexus", "--server"]


def test_plain_nexus_routes_to_ink_tui(monkeypatch, tmp_path):
    import nexus

    nexus._mark_setup_complete(str(tmp_path), "setup")
    called = {}

    monkeypatch.setattr(sys, "argv", ["nexus"])
    monkeypatch.setattr(nexus, "_setup_environment", lambda: str(tmp_path))
    monkeypatch.setattr(nexus, "_run_ink_tui", lambda root, console: called.setdefault("ink", root) or 0)
    monkeypatch.setattr(nexus, "_run_rich_shell", lambda: called.setdefault("shell", True) or 0)

    with pytest.raises(SystemExit):
        nexus.boot()

    assert called["ink"] == str(tmp_path)
    assert "shell" not in called


def test_shell_alias_routes_to_rich_shell(monkeypatch, tmp_path):
    import nexus

    nexus._mark_setup_complete(str(tmp_path), "setup")
    called = {}

    monkeypatch.setattr(sys, "argv", ["nexus-shell"])
    monkeypatch.setattr(nexus, "_setup_environment", lambda: str(tmp_path))
    monkeypatch.setattr(nexus, "_run_ink_tui", lambda root, console: called.setdefault("ink", root) or 0)
    monkeypatch.setattr(nexus, "_run_rich_shell", lambda: called.setdefault("shell", True) or 0)

    with pytest.raises(SystemExit):
        nexus.boot()

    assert called["shell"] is True
    assert "ink" not in called


def test_windows_npm_resolver_prefers_cmd(monkeypatch):
    import nexus

    monkeypatch.setattr(nexus.os, "name", "nt", raising=False)

    def fake_which(name):
        return {
            "npm.cmd": "C:/Program Files/nodejs/npm.cmd",
            "npm": "C:/Program Files/nodejs/npm",
        }.get(name)

    monkeypatch.setattr(nexus.shutil, "which", fake_which)

    assert nexus._find_npm_executable() == "C:/Program Files/nodejs/npm.cmd"


def test_tui_runner_prefers_local_tsx(monkeypatch, tmp_path):
    import nexus

    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    tsx = bin_dir / ("tsx.cmd" if nexus.os.name == "nt" else "tsx")
    tsx.write_text("", encoding="utf-8")

    assert nexus._find_tui_runner(str(tmp_path)) == [str(tsx), "nexus-tui.tsx"]


def test_ink_tui_starts_without_waiting_for_api(monkeypatch, tmp_path):
    import nexus

    tui_dir = tmp_path / "tui"
    tui_dir.mkdir()
    (tui_dir / "nexus-tui.tsx").write_text("// test", encoding="utf-8")
    calls = []

    monkeypatch.setattr(nexus, "_api_is_ready", lambda: False)
    monkeypatch.setattr(nexus, "_kill_windows_port", lambda port: calls.append(("kill", port)))
    monkeypatch.setattr(nexus, "_find_tui_runner", lambda path: ["runner", "nexus-tui.tsx"])
    monkeypatch.setattr(nexus.asyncio, "run", lambda *args, **kwargs: calls.append("waited"))

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append("backend")
            self.running = True
            self.pid = None

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            calls.append("terminated")
            self.running = False

        def wait(self, timeout=None):
            return 0

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: calls.append(("tui", args[0])) or FakeCompleted())

    assert nexus._run_ink_tui(str(tmp_path), console=None) == 0
    assert calls == [("kill", 8000), "backend", ("tui", ["runner", "nexus-tui.tsx"]), "terminated"]


def test_ink_tui_propagates_dashboard_token_to_children(monkeypatch, tmp_path):
    import os
    import subprocess
    import nexus

    tui_dir = tmp_path / "tui"
    tui_dir.mkdir()
    (tui_dir / "nexus-tui.tsx").write_text("// test", encoding="utf-8")
    token = "token-for-test-only"
    captured = {}

    monkeypatch.setattr(nexus.secrets, "token_urlsafe", lambda size: token)
    monkeypatch.setattr(nexus, "_api_is_ready", lambda *_args: False)
    monkeypatch.setattr(nexus, "_kill_windows_port", lambda port: captured.setdefault("killed", port))
    monkeypatch.setattr(nexus, "_find_tui_runner", lambda path: ["runner", "nexus-tui.tsx"])

    class FakePopen:
        pid = None

        def __init__(self, args, **kwargs):
            captured["backend_args"] = args
            captured["backend_kwargs"] = kwargs
            self.running = True

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.running = False

        def wait(self, timeout=None):
            self.running = False
            return 0

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    def fake_run(args, **kwargs):
        captured["tui_args"] = args
        captured["tui_kwargs"] = kwargs
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    cleaned = []
    monkeypatch.setattr(nexus, "_terminate_server_process", lambda proc: cleaned.append(proc))
    before = os.environ.copy()

    assert nexus._run_ink_tui(str(tmp_path), console=None) == 0

    assert captured["killed"] == 8000
    assert captured["backend_args"][:3] == [nexus.sys.executable, "-m", "uvicorn"]
    assert captured["tui_args"] == ["runner", "nexus-tui.tsx"]
    assert captured["backend_kwargs"]["env"]["NEXUS_DASHBOARD_TOKEN"] == token
    assert captured["tui_kwargs"]["env"]["NEXUS_DASHBOARD_TOKEN"] == token
    assert os.environ == before
    assert len(cleaned) == 1


def test_server_launcher_owns_process_group_and_reaps_child(monkeypatch):
    import nexus

    kwargs = nexus._server_process_group_kwargs()
    if nexus.os.name == "nt":
        assert "creationflags" in kwargs
    else:
        assert kwargs == {"start_new_session": True}

    class FakeProcess:
        pid = None

        def __init__(self):
            self.running = True
            self.terminated = False
            self.waited = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            self.waited = True
            return 0

    process = FakeProcess()
    nexus._terminate_server_process(process)

    assert process.terminated
    assert process.waited


def test_gui_foreground_process_is_reaped(monkeypatch, tmp_path):
    import subprocess
    import nexus

    calls = []

    class FakeProcess:
        pid = None

        def __init__(self):
            self.running = True

        def poll(self):
            return None if self.running else 0

        def wait(self, timeout=None):
            calls.append("wait")
            self.running = False
            return 0

        def terminate(self):
            calls.append("terminate")
            self.running = False

    process = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    assert nexus._run_owned_foreground_process(["npm", "run", "dev"], str(tmp_path)) == 0
    assert calls == ["wait"]


def test_stale_gui_port_cleanup_is_not_windows_only(monkeypatch):
    import sys
    import types
    import nexus

    events = []

    class Child:
        def terminate(self):
            events.append("child-terminate")

        def kill(self):
            events.append("child-kill")

    class Process:
        pid = 123

        def cmdline(self):
            return ["node", "vite", "--port", "5173"]

        def children(self, recursive=False):
            return [Child()]

        def terminate(self):
            events.append("parent-terminate")

        def kill(self):
            events.append("parent-kill")

    fake_psutil = types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        AccessDenied=RuntimeError,
        NoSuchProcess=RuntimeError,
        net_connections=lambda kind="tcp": [
            types.SimpleNamespace(status="LISTEN", laddr=types.SimpleNamespace(port=5173), pid=123)
        ],
        Process=lambda pid: Process(),
        wait_procs=lambda processes, timeout=3.0: (processes, []),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    nexus._kill_windows_port(5173)

    assert events == ["child-terminate", "parent-terminate"]
