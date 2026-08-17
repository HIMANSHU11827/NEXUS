import subprocess

from models.providers.auth.opencode_cli import OpenCodeCLIProvider


class _FakeProcess:
    def __init__(self, stdout="", stderr="", returncode=0, timed_out=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timed_out = timed_out
        self.killed = False
        self.waited = False
        self.pid = None
        self.kwargs = {}

    def communicate(self, timeout=None):
        if self._timed_out and not self.killed:
            raise subprocess.TimeoutExpired("opencode", timeout)
        return self._stdout, self._stderr

    def poll(self):
        if self._timed_out and not self.killed:
            return None
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


def _provider():
    provider = object.__new__(OpenCodeCLIProvider)
    provider._cli_path = "opencode.cmd"
    return provider


def test_opencode_cli_provider_cleans_terminal_footer(monkeypatch):
    provider = _provider()
    process = _FakeProcess("NEXUS OK\n\x1b[0m\n> plan Â· free\n")
    monkeypatch.setattr(
        "models.providers.auth.opencode_cli.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    assert provider.generate(messages=[{"role": "user", "content": "hello"}]) == "NEXUS OK"


def test_opencode_cli_provider_reports_process_failure(monkeypatch):
    provider = _provider()
    process = _FakeProcess("", "not authenticated", returncode=1)
    monkeypatch.setattr(
        "models.providers.auth.opencode_cli.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    assert provider.generate(prompt="hello").startswith(
        "Error: OpenCode CLI failed: not authenticated"
    )


def test_opencode_cli_provider_passes_process_ownership_and_cleans_timeout(monkeypatch):
    provider = _provider()
    process = _FakeProcess(timed_out=True)

    def fake_popen(*args, **kwargs):
        process.kwargs = kwargs
        return process

    monkeypatch.setattr("models.providers.auth.opencode_cli.subprocess.Popen", fake_popen)

    result = provider.generate(prompt="hello", timeout=0.01)

    assert result == "Error: OpenCode CLI timed out after 0.01s."
    assert process.killed
    assert process.waited
    assert "creationflags" in process.kwargs or process.kwargs.get("start_new_session") is True
