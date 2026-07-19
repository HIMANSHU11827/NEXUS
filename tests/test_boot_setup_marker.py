import json
import sys
from pathlib import Path

import pytest


def test_setup_complete_marker_disables_first_run(tmp_path):
    import nexus

    config_dir = tmp_path / "config"
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
    assert (tmp_path / "config" / ".env").exists()
    assert (tmp_path / "config" / "provider.yml").exists()
    assert (tmp_path / "config" / "settings.yml").exists()
    settings = (tmp_path / "config" / "settings.yml").read_text(encoding="utf-8")
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

        def terminate(self):
            calls.append("terminated")

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: calls.append(("tui", args[0])) or FakeCompleted())

    assert nexus._run_ink_tui(str(tmp_path), console=None) == 0
    assert calls == [("kill", 8000), "backend", ("tui", ["runner", "nexus-tui.tsx"]), "terminated"]
