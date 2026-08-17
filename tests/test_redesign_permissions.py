"""Redesign regression tests for the NEXUS permission/sandbox layer.

Covers the soft-degrading additions to the permission layer:
  (a) ask-mode shell commands route through the human approval broker and
      re-execute on approval (mirroring ``_audit_tool_call``).
  (b) ``pre_tool_call`` plugin hook block directives deny the tool with the
      hook's reason.
  (c) decisions are persisted to the JSONL ledger and rehydrated on the next
      PermissionSystem init.
  (d) per-agent rules loaded from config/permission_agents.yml let an agent
      deny win over the global allow list.
  (e) the DOCKER sandbox tier hardens its run args (--network=none,
      --read-only) and fails closed when Docker is unavailable.

Each test isolates the PermissionSystem singleton and redirects the JSONL
ledger to a temp file so the real ``~/.nexus`` home is never touched. The
Docker subprocess is monkeypatched; nothing here launches a real container.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

# Make the repo root importable regardless of the pytest working directory.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import permissions as permissions_module
from orchestrators.v5.tools import V5ToolExecutor, _TextToolCall
from permissions import PermissionMode, PermissionSystem
from permissions.approval_broker import get_approval_broker
from sandbox.sandbox_manager import SovereignSandbox


# ── isolation fixture ────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolate_permission_state(tmp_path, monkeypatch):
    """Redirect the JSONL ledger and reset the singleton per test.

    Keeps tests hermetic: a fresh in-memory log, a fresh agent-rules load, and
    a ledger file under the pytest temp dir so the real home is untouched.
    """
    ledger = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(permissions_module, "DECISIONS_LOG_FILE", str(ledger))
    PermissionSystem._reset_instance()
    yield
    PermissionSystem._reset_instance()


# ── minimal V5 executor harness ─────────────────────────────────────────────
class _FakeSandbox:
    """In-memory sandbox that records commands and returns a canned chunk."""

    def __init__(self):
        self.calls = []
        self.last_exit_code = 0

    async def stream_execute(self, command, workdir=None, timeout=None):
        self.calls.append((command, workdir))
        yield f"OUT:{command}"


class _FakeRuntime:
    def __init__(self, sandbox=None, permissions=None, risk_scorer=None):
        self.sandbox = sandbox
        self.permissions = permissions
        self.risk_scorer = risk_scorer
        self.work_event_sink = None
        self.hooks = None


class _FakeExecutor(V5ToolExecutor):
    """V5ToolExecutor backed by a fake runtime; events are recorded in-memory."""

    def __init__(self, runtime, *, session_id="sess-approve"):
        self.runtime = runtime
        self.session_id = session_id
        self.root_dir = str(_ROOT)
        self._current_turn_id = "run-1"
        self._stream_events = []
        self._tool_started_at = {}
        self._stage_started_at = {}
        self._approved_calls = {}
        self.kernel = None
        self.tool_registry = None
        self.logger = logging.getLogger("test_redesign_permissions")

    async def _emit_tool_event(
        self, call, *, status, result="", error="", exit_code=None, background=False
    ):
        self._stream_events.append({"event_type": "tool.call", "tool": call.name, "status": status})

    async def _emit_tool_chunk(self, call, text, sequence, stream="stdout"):
        self._stream_events.append({"event_type": "tool.chunk", "tool": call.name, "chunk": text})

    async def _emit_work_event(self, payload):
        self._stream_events.append(dict(payload))

    async def _fire_post_tool_hooks(self, call, status, result="", error=""):
        return None


# ── (a) ask-mode command routes to the broker and re-executes on approval ───
def test_ask_mode_command_routes_to_broker_and_reexecutes():
    async def scenario():
        system = PermissionSystem()
        system.set_mode(PermissionMode.APPROVE)
        sandbox = _FakeSandbox()
        runtime = _FakeRuntime(sandbox=sandbox, permissions=system, risk_scorer=None)
        executor = _FakeExecutor(runtime, session_id="sess-approve-a")

        call = _TextToolCall("bash", {"command": "echo approved"}, "call-1")
        task = asyncio.create_task(executor._run_tool(call))

        # Wait for the broker to surface the approval request for this session.
        pending = []
        for _ in range(100):
            pending = get_approval_broker().pending("sess-approve-a")
            if pending:
                break
            await asyncio.sleep(0.01)
        assert pending, "ask-mode command should open an approval request"
        request_id = pending[0]["request_id"]

        # A human approves; the command must then re-execute through the sandbox.
        assert get_approval_broker().resolve(request_id, "yes") is True
        result = await asyncio.wait_for(task, timeout=5)
        assert "OUT:echo approved" in result
        assert sandbox.calls and sandbox.calls[0][0] == "echo approved"

        # The ledger records both the ask-mode denial and the human verdict.
        log = system.get_decision_log(50)
        sources = [entry.get("source") for entry in log]
        assert "mode:manual_approval" in sources
        assert "mode:human_approval" in sources

    asyncio.run(scenario())


def test_ask_mode_command_denied_when_human_denies():
    async def scenario():
        system = PermissionSystem()
        system.set_mode(PermissionMode.APPROVE)
        sandbox = _FakeSandbox()
        runtime = _FakeRuntime(sandbox=sandbox, permissions=system, risk_scorer=None)
        executor = _FakeExecutor(runtime, session_id="sess-approve-deny")

        call = _TextToolCall("bash", {"command": "echo no"}, "call-2")
        task = asyncio.create_task(executor._run_tool(call))

        pending = []
        for _ in range(100):
            pending = get_approval_broker().pending("sess-approve-deny")
            if pending:
                break
            await asyncio.sleep(0.01)
        assert pending, "a denial should still surface an approval request"
        request_id = pending[0]["request_id"]

        assert get_approval_broker().resolve(request_id, "no") is True
        with pytest.raises(RuntimeError) as excinfo:
            await asyncio.wait_for(task, timeout=5)
        assert "Permission denied" in str(excinfo.value)
        assert not sandbox.calls, "command must not execute when the human denies"

    asyncio.run(scenario())


# ── (b) pre_tool_call hook block directives deny the tool ───────────────────
class _FakePlugins:
    def __init__(self, results):
        self.results = results

    async def trigger_hooks(self, event, *args, **kwargs):
        return self.results


class _FakeKernel:
    def __init__(self, results):
        self.plugins = _FakePlugins(results)


def test_pre_tool_call_hook_block_denies():
    async def scenario():
        system = PermissionSystem()
        system.set_mode(PermissionMode.BYPASS)  # global would allow everything
        executor = _FakeExecutor(_FakeRuntime(permissions=system))

        executor.kernel = _FakeKernel([{"action": "block", "reason": "policy forbids"}])
        call = _TextToolCall("reading", {"path": "x.txt"}, "call-b1")
        assert await executor._audit_tool_call(call) is False
        assert call._denied_reason == "policy forbids"

        executor.kernel = _FakeKernel([{"block": True, "message": "vetoed"}])
        call = _TextToolCall("reading", {"path": "y.txt"}, "call-b2")
        assert await executor._audit_tool_call(call) is False
        assert call._denied_reason == "vetoed"

    asyncio.run(scenario())


def test_non_blocking_hook_result_is_ignored():
    async def scenario():
        system = PermissionSystem()
        system.set_mode(PermissionMode.BYPASS)
        executor = _FakeExecutor(_FakeRuntime(permissions=system))
        executor.kernel = _FakeKernel([{"action": "allow"}, None])
        call = _TextToolCall("reading", {"path": "z.txt"}, "call-b3")
        assert await executor._audit_tool_call(call) is True

    asyncio.run(scenario())


# ── (c) decisions persisted to JSONL and reloaded ───────────────────────────
def test_decision_jsonl_persisted_and_reloaded():
    PermissionSystem._reset_instance()
    system = PermissionSystem()
    system.set_mode(PermissionMode.AUTO_PILOT)
    system.add_rule("deleting", "*", granted=False)  # exercises matched_rule

    allow = system.check("bash", "echo persisted", context={"session_id": "s9", "surface": "cli"})
    assert allow.granted is True
    deny = system.check("deleting", "rm -rf build", context={"session_id": "s9"})
    assert deny.granted is False

    # The JSONL ledger holds one valid line per decision.
    ledger = Path(permissions_module.DECISIONS_LOG_FILE)
    assert ledger.exists()
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool"] == "bash"
    assert first["granted"] is True
    assert first["action_preview"] == "echo persisted"
    assert first["session_id"] == "s9"
    assert first["surface"] == "cli"
    assert isinstance(first["timestamp"], (int, float))

    # Simulate a new process: fresh singleton rehydrates from the same ledger.
    PermissionSystem._reset_instance()
    system2 = PermissionSystem()
    log = system2.get_decision_log(50)
    tools = {entry.get("tool") for entry in log}
    assert tools >= {"bash", "deleting"}
    deleting = next(e for e in log if e["tool"] == "deleting")
    assert deleting["matched_rule"]["granted"] is False
    assert isinstance(deleting["timestamp"], (int, float))


def test_decision_persistence_degrades_when_io_fails(monkeypatch):
    """An unwritable ledger path must not break the permission decision."""
    # A NUL byte in the path makes every open/makedirs fail on Windows.
    monkeypatch.setattr(
        permissions_module,
        "DECISIONS_LOG_FILE",
        "C:\\nonexistent\x00ledger\\decisions.jsonl",
    )
    PermissionSystem._reset_instance()
    system = PermissionSystem()
    system.set_mode(PermissionMode.BYPASS)
    result = system.check("bash", "echo still-works")
    assert result.granted is True


# ── (d) per-agent deny wins over global allow ───────────────────────────────
def test_agent_deny_wins_over_global_allow():
    system = PermissionSystem()
    system.set_mode(PermissionMode.BYPASS)
    system.add_rule("bash", "*", granted=True)  # global allow for bash
    system.agent_rules = {"strict_agent": {"deny": ["bash"], "allow": []}}

    denied = system.check("bash", "ls", agent_id="strict_agent")
    assert denied.granted is False
    assert denied.decision.get("source") == "agent:deny"

    # Global behavior is unchanged when no agent_id is supplied.
    allowed = system.check("bash", "ls")
    assert allowed.granted is True

    # An unknown agent is not restricted.
    unknown = system.check("bash", "ls", agent_id="mystery_agent")
    assert unknown.granted is True


def test_agent_rules_loaded_from_config(tmp_path, monkeypatch):
    cfg = tmp_path / "permission_agents.yml"
    cfg.write_text(
        "agents:\n"
        "  strict_agent:\n"
        "    deny:\n"
        "      - bash\n"
        "    allow:\n"
        "      - reading\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(permissions_module, "DEFAULT_AGENT_RULES_FILE", str(cfg))
    PermissionSystem._reset_instance()
    system = PermissionSystem()
    system.set_mode(PermissionMode.BYPASS)

    assert "strict_agent" in system.get_agent_rules()
    assert system.check("bash", "anything", agent_id="strict_agent").granted is False
    # A tool not in the deny list is unaffected.
    assert system.check("reading", "x.txt", agent_id="strict_agent").granted is True


def test_missing_agent_config_yields_empty_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(permissions_module, "DEFAULT_AGENT_RULES_FILE", str(tmp_path / "missing.yml"))
    PermissionSystem._reset_instance()
    system = PermissionSystem()
    system.set_mode(PermissionMode.BYPASS)
    assert system.get_agent_rules() == {}
    assert system.check("bash", "ls", agent_id="any").granted is True


# ── (e) DOCKER sandbox tier hardening ───────────────────────────────────────
class _FakeCompleted:
    def __init__(self, args, returncode=0, stdout="", stderr=""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_docker_run_args_include_network_none_and_read_only(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        args_list = list(args)
        calls.append(args_list)
        if "info" in args_list:
            return _FakeCompleted(args_list, returncode=0, stdout="Server: 27")
        return _FakeCompleted(args_list, returncode=0, stdout="hello container\n")

    monkeypatch.setattr("sandbox.sandbox_manager.subprocess.run", fake_run)
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "docker")
    sandbox = SovereignSandbox(root_dir=str(tmp_path))

    result = sandbox.execute("echo hi", workdir=str(tmp_path))

    run_calls = [args for args in calls if "run" in args]
    assert run_calls, "docker run should be attempted when the daemon is present"
    run_args = run_calls[0]
    assert "--network=none" in run_args
    assert "--read-only" in run_args
    assert '"echo hi"' in result or "hello container" in result


def test_docker_fails_closed_when_docker_missing(monkeypatch, tmp_path):
    import subprocess as sp

    calls = []

    def fake_run(args, **kwargs):
        args_list = list(args)
        calls.append(args_list)
        if "info" in args_list:
            raise sp.CalledProcessError(1, args_list)  # daemon unavailable
        return _FakeCompleted(args_list, returncode=0, stdout="should not run")

    monkeypatch.setattr("sandbox.sandbox_manager.subprocess.run", fake_run)
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "docker")
    sandbox = SovereignSandbox(root_dir=str(tmp_path))

    result = sandbox.execute("echo hi", workdir=str(tmp_path))

    assert "[SANDBOX_BLOCK]" in result and "Failing closed" in result
    # No silent fallback to host-restricted: only the docker info probe ran.
    assert len(calls) == 1 and "info" in calls[0]
    assert not any("echo hi" in a for a in calls)
