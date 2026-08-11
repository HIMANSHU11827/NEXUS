import subprocess

from providers.commandcode import CommandCodeProvider


class _FakeProcess:
    pid = None

    def __init__(self, *, timeout=False):
        self.returncode = None
        self.killed = False
        self.waited = False
        self.timeout = timeout
        self.stdin = self
        self.stdout = self
        self.stderr = self

    def communicate(self, input=None, timeout=None):
        if self.timeout:
            raise subprocess.TimeoutExpired("command-code", timeout)
        self.returncode = 0
        return "ok", ""

    def write(self, _value):
        return None

    def close(self):
        return None

    def readline(self):
        return ""

    def read(self):
        return ""

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("command-code", timeout)
        return self.returncode


def _provider():
    provider = object.__new__(CommandCodeProvider)
    provider._cmd_path = "command-code"
    provider.api_key = ""
    provider.endpoint = ""
    return provider


def test_commandcode_unary_timeout_terminates_and_reaps_process(monkeypatch):
    process = _FakeProcess(timeout=True)
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append(kwargs)
        return process

    monkeypatch.setattr("providers.commandcode.subprocess.Popen", fake_popen)
    result = _provider()._invoke_cmd("hello", timeout=2)

    assert "timed out" in result.lower()
    assert process.killed is True
    assert process.waited is True
    assert calls and ("creationflags" in calls[0] or calls[0].get("start_new_session") is True)


def test_commandcode_stream_timeout_terminates_and_reaps_process(monkeypatch):
    process = _FakeProcess(timeout=True)
    monkeypatch.setattr("providers.commandcode.subprocess.Popen", lambda *args, **kwargs: process)

    result = list(_provider().stream_generate(prompt="hello", timeout=2))

    assert result and "timed out" in result[-1].lower()
    assert process.killed is True
    assert process.waited is True
