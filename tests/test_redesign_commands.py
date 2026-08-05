"""Tests for the redesign slash commands added to nexus/commands.py.

Each new command handler must return a non-empty string and must never raise,
even against a temp / empty session state. State is fabricated under
``tmp_path`` and routed to the handlers via ``CommandContext.extra["root"]``.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus.commands import CommandContext, get_registry

# The commands added in the redesign (agents already existed but was rewired).
NEW_COMMANDS = [
    "compact",
    "context",
    "resume",
    "plans",
    "agents",
    "rewind",
    "hooks",
    "mcp",
    "login",
    "cost",
]


def _build_state(root: Path) -> None:
    """Fabricate realistic session / checkpoint / config / plan state."""
    # logs/sessions/latest.json — newest session file (for /context and /cost).
    sessions = root / "logs" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "latest.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "Hello NEXUS, please estimate context tokens."},
                {"role": "assistant", "content": "Reporting context usage now."},
                {"role": "user", "content": "One more message for the cost estimate."},
            ]
        ),
        encoding="utf-8",
    )
    # .nexus_v5/checkpoints/turn_abc_planning.json — for /resume and /rewind.
    checkpoints = root / ".nexus_v5" / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    (checkpoints / "turn_abc_planning.json").write_text(
        json.dumps(
            {
                "turn_id": "turn_abc",
                "phase": "planning",
                "ts": 1785856000.0,
                "session": "test",
                "context_summary": "Prior turn summary text.",
                "plan": [{"description": "Step one", "tool": "", "params": {}}],
                "actions": ["do-the-thing"],
            }
        ),
        encoding="utf-8",
    )
    # config/mcp_servers.json — for /mcp.
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "mcp_servers.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "filesystem",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    # .claude/agents/test-agent.md — for /agents fallback listing.
    agents_dir = root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "test-agent.md").write_text(
        "# test-agent\n\nA specialist agent for testing.", encoding="utf-8"
    )
    # todo.md plan — for /plans.
    (root / "todo.md").write_text(
        "TODO LIST\n\nTASK NAME: Build evidence.\nPLAN TYPE: Simple\n\n"
        "1. [ ] Step one\n2. [ ] Step two\n",
        encoding="utf-8",
    )


def _make_ctx(root: Path, name: str) -> CommandContext:
    shell = SimpleNamespace(
        conversation_history=[
            {"role": "user", "content": "Hello NEXUS, please estimate context tokens."},
            {"role": "assistant", "content": "Compaction path test."},
            {"role": "user", "content": "A third message to compact."},
        ],
        brain=SimpleNamespace(root=str(root)),
    )
    extra = {"root": str(root)}
    if name == "login":
        extra["args"] = "/login nonexistent-provider-xyz"
    return CommandContext(session_id="test", loop=None, shell=shell, extra=extra)


@pytest.mark.parametrize("name", NEW_COMMANDS)
def test_new_commands_return_text_and_never_raise(tmp_path, name):
    _build_state(tmp_path)
    reg = get_registry()
    cmd = reg.get(name)
    assert cmd is not None, f"/{name} must be registered"

    ctx = _make_ctx(tmp_path, name)
    result = asyncio.run(cmd.execute(ctx))

    assert isinstance(result.output, str)
    assert result.output.strip() != "", f"/{name} returned an empty output"
    # Every command except /login is expected to succeed against real state.
    if name != "login":
        assert result.success, f"/{name} failed: {result.error}"


def test_handlers_degrade_softly_on_empty_state(tmp_path):
    """With no state, handlers must still return text and never raise."""
    reg = get_registry()
    ctx = CommandContext(session_id="fresh", loop=None, shell=None, extra={"root": str(tmp_path)})
    for name in NEW_COMMANDS:
        if name == "compact":
            ctx.shell = SimpleNamespace(conversation_history=[], brain=SimpleNamespace(root=str(tmp_path)))
        result = asyncio.run(reg.execute(name, ctx))
        assert isinstance(result.output, str), f"/{name} produced no text output"
        assert result.output.strip() != "", f"/{name} returned an empty output on empty state"
