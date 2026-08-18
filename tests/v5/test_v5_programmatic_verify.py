import asyncio
import json
import time
from types import SimpleNamespace

import nexus.main_agent.programmatic_verify as programmatic_verify
from nexus.main_agent.verification_events import VerifierEventStore
from nexus.main_agent.verification_state import VerifierStateStore


class _FakeSandbox:
    def __init__(self, root):
        self.root = root
        self.tier = SimpleNamespace(value="normal")
        self.last_exit_code = None

    async def stream_execute(self, command, workdir, timeout=None, shell=None):
        self.last_exit_code = 2 if "fail" in command else 0
        yield "Bearer secret-token\n" if "secret" in command else "verification output\n"


def test_programmatic_verification_persists_trusted_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest tests/unit -q"], session_id="session-1"
    ))
    assert result.success is True
    assert result.status == "passed"
    assert result.run_id.startswith("vr_")
    assert result.event_id.startswith("ve_")
    assert result.commands[0].scope == "targeted"
    assert "secret-token" not in json.dumps(result.to_dict())
    events = VerifierEventStore(tmp_path / ".nexus" / "v5" / "verifier_events.sqlite3").list_events(
        "session-1", str(tmp_path)
    )
    assert events[0]["status"] == "passed"
    state = VerifierStateStore(tmp_path / ".nexus" / "v5" / "verifier_state.json").get(
        "session-1", str(tmp_path)
    )
    assert state["status"] == "passed"
    assert state["last_event_id"] == result.event_id


def test_programmatic_verification_fails_on_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest fail -q"], session_id="session-2"
    ))
    assert result.success is False
    assert result.status == "failed"
    assert result.commands[0].exit_code == 2
    assert result.durable_status == "failed"


def test_programmatic_verification_does_not_claim_untrusted_or_chained_pass(tmp_path, monkeypatch):
    class _NoExitSandbox(_FakeSandbox):
        async def stream_execute(self, command, workdir, timeout=None, shell=None):
            self.last_exit_code = None
            yield "finished"

    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _NoExitSandbox)
    missing_exit = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest -q"], session_id="session-3"
    ))
    assert missing_exit.status == "unverified"
    assert missing_exit.event_id == ""

    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    chained = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest -q && echo done"], session_id="session-4"
    ))
    assert chained.status == "unverified"
    assert chained.commands[0].status == "unverified"


def test_programmatic_verification_does_not_self_authorize_unknown_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["echo verification"], session_id="session-5"
    ))
    assert result.status == "unverified"
    assert result.event_id == ""


def test_programmatic_verification_status_precedence_is_failed_then_unverified(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path,
        [{"command": "echo unknown", "phase": "build"}, {"command": "pytest fail -q", "phase": "test"}],
        session_id="session-6", stop_on_failure=False,
    ))
    assert result.status == "failed"
    assert result.commands[0].phase == "build"
    assert result.commands[1].phase == "test"
    assert result.commands[1].kind == "test"


def test_programmatic_verification_rejects_non_loopback_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest -q"], readiness_url="https://example.com/health",
    ))
    assert result.status == "failed"
    assert result.success is False
    assert result.readiness.ready is False
    assert "localhost" in result.readiness.error


def test_programmatic_verification_records_loopback_readiness(tmp_path, monkeypatch):
    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    monkeypatch.setattr(programmatic_verify.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())
    result = asyncio.run(programmatic_verify.run_programmatic_verification(
        tmp_path, ["pytest -q"], readiness_url="http://127.0.0.1:8000/health",
    ))
    assert result.success is True
    assert result.readiness.ready is True
    assert result.readiness.status_code == 204


def test_readiness_probe_does_not_block_async_verification_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    ticks = 0
    done = False

    def slow_probe(url, timeout):
        time.sleep(0.12)
        return programmatic_verify.VerificationReadinessFact(
            url=url, ready=True, status_code=200, duration_seconds=0.12
        )

    monkeypatch.setattr(programmatic_verify, "_probe_readiness", slow_probe)

    async def scenario():
        nonlocal ticks, done

        async def heartbeat():
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            result = await programmatic_verify.run_programmatic_verification(
                tmp_path,
                ["pytest -q"],
                readiness_url="http://127.0.0.1:8000/health",
            )
        finally:
            done = True
            await heartbeat_task
        assert result.readiness.ready is True

    asyncio.run(scenario())
    assert ticks >= 5


def test_detected_verification_uses_recipe_checks_without_starting_process(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setattr(programmatic_verify, "SovereignSandbox", _FakeSandbox)
    result = asyncio.run(programmatic_verify.run_detected_verification(tmp_path))
    assert result.success is True
    assert result.recipe_source == "detected"
    assert result.recipe_name == "Python project"
