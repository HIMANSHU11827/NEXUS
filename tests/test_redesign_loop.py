"""Tests for the NEXUS/Claude-Code comparison redesign of the V5 direct loop.

Covers the four new behaviors added to keep the loop bounded and resilient:
  (a) oversized tool results are archived and replaced by a preview,
  (b) empty tool results become an explicit "no output" marker,
  (c) prompt-too-long provider errors trigger one compact-and-retry, and
  (d) checkpoints now carry ``recent_messages`` for a future ``continue``.

All network/model calls are monkeypatched; nothing here touches the network.
"""

import asyncio
import json
import os
import time
import threading

from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.direct_loop import (
    MAX_TOOL_RESULT_CHARS,
    TOOL_RESULT_PREVIEW_CHARS,
    V5DirectModelToolLoop,
)


def _native(name, args, call_id):
    return {
        "choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                             "function": {"name": name, "arguments": args}}],
        }}]
    }


# ─────────────────────────────────────────────────────────────────────────
# (a) oversized tool result is archived and replaced by a preview
# ─────────────────────────────────────────────────────────────────────────

def test_oversized_tool_result_is_archived_and_previewed_in_loop(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="archive-loop-test")
    loop._current_turn_id = "turn-archive"
    replies = iter([
        _native("fixture_tool", "{}", "call-big"),
        {"choices": [{"message": {"content": "done"}}]},
    ])

    async def model(messages, **kwargs):
        return next(replies)

    async def tool(call):
        return "x" * 60_000

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("run big", max_rounds=1))

    assert result["success"] is True
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert "[result 60000 chars persisted to" in tool_message["content"]
    assert f"showing first {TOOL_RESULT_PREVIEW_CHARS} chars" in tool_message["content"]
    # The bounded transcript must not contain the full 60k payload.
    assert "x" * 60_000 not in tool_message["content"]

    archive = tmp_path / ".nexus" / "context_archive" / "tool-results" / "turn-archive_0.txt"
    assert archive.exists()
    assert archive.read_text(encoding="utf-8") == "x" * 60_000


def test_oversized_tool_result_archive_degrades_to_original_on_error(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="archive-degrade-test")
    # Force the archive write to fail by making the base path unwritable.
    blocking = tmp_path / ".nexus" / "context_archive"
    blocking.mkdir(parents=True)
    (blocking / "tool-results").write_text("not a dir", encoding="utf-8")
    content = "y" * (MAX_TOOL_RESULT_CHARS + 5)
    bounded = loop._bounded_tool_result(
        content, "fixture_tool", "turn-x", 1, str(tmp_path)
    )
    assert bounded == content


def test_async_tool_result_archiving_does_not_block_event_loop(monkeypatch, tmp_path):
    original = V5DirectModelToolLoop._bounded_tool_result

    def slow_bounded(cls, content, tool_name, turn_id, call_slot, root_dir=""):
        time.sleep(0.08)
        return original.__func__(cls, content, tool_name, turn_id, call_slot, root_dir)

    monkeypatch.setattr(
        V5DirectModelToolLoop, "_bounded_tool_result",
        classmethod(slow_bounded),
    )

    async def exercise():
        ticks = 0
        finished = asyncio.Event()

        async def heartbeat():
            nonlocal ticks
            while not finished.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(heartbeat())
        result = await V5DirectModelToolLoop._bounded_tool_result_async(
            "z" * (MAX_TOOL_RESULT_CHARS + 1), "fixture", "turn", 0, str(tmp_path)
        )
        finished.set()
        await task
        return result, ticks

    result, ticks = asyncio.run(exercise())
    assert "persisted to" in result
    assert ticks >= 3


def test_async_direct_message_persistence_does_not_block_event_loop(monkeypatch, tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="async-persist-test")
    original = loop._write_session_bus

    def slow_write(*args, **kwargs):
        time.sleep(0.08)
        return original(*args, **kwargs)

    monkeypatch.setattr(loop, "_write_session_bus", slow_write)

    async def exercise():
        ticks = 0
        finished = asyncio.Event()

        async def heartbeat():
            nonlocal ticks
            while not finished.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(heartbeat())
        await loop._persist_direct_message_async(
            {"role": "tool", "name": "fixture", "tool_call_id": "call-1", "content": "ok"},
            "turn-1",
        )
        finished.set()
        await task
        return ticks

    ticks = asyncio.run(exercise())
    assert ticks >= 3
    assert any(item.get("tool_call_id") == "call-1" for item in loop.runtime.memory)


def test_async_turn_message_persistence_does_not_block_event_loop(monkeypatch, tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="async-turn-persist-test")
    original = loop._write_session_bus

    def slow_write(*args, **kwargs):
        time.sleep(0.08)
        return original(*args, **kwargs)

    monkeypatch.setattr(loop, "_write_session_bus", slow_write)

    async def exercise():
        ticks = 0
        finished = asyncio.Event()

        async def heartbeat():
            nonlocal ticks
            while not finished.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(heartbeat())
        await loop._persist_turn_message_async("user", "hello", "turn-2")
        finished.set()
        await task
        return ticks

    ticks = asyncio.run(exercise())
    assert ticks >= 3
    assert any(item.get("turn_id") == "turn-2" for item in loop.runtime.memory)


def test_session_bus_replacement_uses_cross_process_mutex(tmp_path):
    first = NexusLoopV5(str(tmp_path), session_id="shared-session")
    second = NexusLoopV5(str(tmp_path), session_id="shared-session")
    first.runtime.memory = [{"role": "user", "content": "first"}]
    second.runtime.memory = [{"role": "user", "content": "second"}]
    path = os.path.join(str(tmp_path), ".nexus", "logs", "sessions", "shared-session.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entered = first._session_bus_interprocess_lock(path)
    entered.__enter__()
    completed = threading.Event()

    def write_from_other_process():
        second._write_session_bus()
        completed.set()

    worker = threading.Thread(target=write_from_other_process, daemon=True)
    worker.start()
    try:
        assert not completed.wait(0.08)
    finally:
        entered.__exit__(None, None, None)
    worker.join(timeout=2.0)
    assert completed.is_set()
    assert os.path.isfile(path + ".lock.sqlite")
    assert json.loads(open(path, encoding="utf-8").read()) == second.runtime.memory


def test_v5_session_id_cannot_escape_session_directory(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="../../outside.json")

    assert loop.session_id == "outside"
    loop._persist_turn_message("user", "safe", "turn-safe")

    expected = tmp_path / ".nexus" / "logs" / "sessions" / "outside.json"
    escaped = tmp_path.parent / "outside.json"
    assert expected.exists()
    assert not escaped.exists()

    loop.load_memory("../../reloaded.json")
    assert loop.session_id == "reloaded"
    assert loop.runtime.session_id == "reloaded"


# ─────────────────────────────────────────────────────────────────────────
# (b) empty tool result becomes an explicit no-output marker
# ─────────────────────────────────────────────────────────────────────────

def test_empty_tool_result_becomes_no_output_marker_in_loop(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="no-output-loop-test")
    replies = iter([
        _native("fixture_tool", "{}", "call-empty"),
        {"choices": [{"message": {"content": "done"}}]},
    ])

    async def model(messages, **kwargs):
        return next(replies)

    async def tool(call):
        return "   "

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("run empty", max_rounds=1))

    assert result["success"] is True
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert tool_message["content"] == "(fixture_tool completed with no output)"


def test_empty_tool_result_marker_matches_whitespace(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="no-output-marker-test")
    assert loop._bounded_tool_result("", "grep", "t", 0, str(tmp_path)) == \
        "(grep completed with no output)"
    assert loop._bounded_tool_result(" \n\t ", "terminal", "t", 0, str(tmp_path)) == \
        "(terminal completed with no output)"
    # Normal content is returned unchanged and never archived.
    assert loop._bounded_tool_result("hello", "grep", "t", 0, str(tmp_path)) == "hello"


# ─────────────────────────────────────────────────────────────────────────
# (c) prompt-too-long triggers one compact-and-retry
# ─────────────────────────────────────────────────────────────────────────

def test_prompt_too_long_compacts_and_retries_once(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="compact-retry-test")
    seen = []

    async def model(messages, **kwargs):
        seen.append(messages)
        return {"choices": [{"message": {"content": "ok"}}]}

    loop._safe_model_call_raw = model
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first prompt"},
        {"role": "assistant", "content": "assistant reply"},
        {"role": "user", "content": "latest prompt"},
    ]
    # First call returns a prompt-too-long provider error; the wrapper must
    # compact the oldest half and retry once, landing on the second answer.
    calls = {"count": 0}

    async def failing_then_ok(model_messages, **kwargs):
        seen.append(model_messages)
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"message": {
                "content": "Error: context length exceeded. Prompt is too long for the model."}}]}
        return {"choices": [{"message": {"content": "recovered"}}]}

    loop._safe_model_call_raw = failing_then_ok
    result = asyncio.run(loop._prompt_too_long_retry(messages, {}))

    assert calls["count"] == 2
    assert len(seen) == 2
    # The retry compacts the oldest half into a system summary.
    assert any("[compacted earlier turns" in str(m.get("content")) for m in seen[1])
    assert "recovered" in str(result)


def test_prompt_too_long_retry_returns_error_when_retry_still_fails(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="compact-retry-fail-test")
    calls = {"count": 0}

    async def always_too_long(model_messages, **kwargs):
        calls["count"] += 1
        return {"choices": [{"message": {
            "content": "prompt is too long (413)"}}]}

    loop._safe_model_call_raw = always_too_long
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    result = asyncio.run(loop._prompt_too_long_retry(messages, {}))

    assert calls["count"] == 2  # one retry, not an infinite loop
    assert "prompt is too long" in str(result)


def test_normal_prompt_does_not_retry(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="no-retry-test")
    calls = {"count": 0}

    async def normal(model_messages, **kwargs):
        calls["count"] += 1
        return {"choices": [{"message": {"content": "a normal answer"}}]}

    loop._safe_model_call_raw = normal
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    result = asyncio.run(loop._prompt_too_long_retry(messages, {}))

    assert calls["count"] == 1
    assert "a normal answer" in str(result)


# ─────────────────────────────────────────────────────────────────────────
# (d) checkpoint payload now carries recent_messages
# ─────────────────────────────────────────────────────────────────────────

def test_checkpoint_payload_includes_recent_messages(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ck-recent-test")
    messages = [
        {"role": msg[0], "content": msg[1]}
        for msg in [
            ("user", "one"), ("assistant", "two"), ("tool", "three"),
            ("user", "four"), ("assistant", "five"),
        ]
    ]
    loop._recent_messages = messages
    path = loop._checkpoint_save(turn_id="turn-recent", phase="act")

    assert path and os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["recent_messages"] == messages
    # Existing keys must still be present (backward compatibility).
    assert data["turn_id"] == "turn-recent"


def test_checkpoint_recent_messages_are_last_twelve(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ck-truncate-test")
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"msg-{i}"}
        for i in range(30)
    ]
    loop._recent_messages = messages
    path = loop._checkpoint_save(turn_id="turn-trunc", phase="act")

    assert path and os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["recent_messages"]) == 12
    assert data["recent_messages"][-1]["content"] == "msg-29"


# ─────────────────────────────────────────────────────────────────────────
# cloud context headroom (bonus safety on the new cloud path)
# ─────────────────────────────────────────────────────────────────────────

def test_cloud_bounded_messages_trims_oldest_when_over_window(tmp_path, monkeypatch):
    loop = NexusLoopV5(str(tmp_path), session_id="cloud-headroom-test")
    monkeypatch.setattr(
        V5DirectModelToolLoop, "_context_window_for_provider",
        staticmethod(lambda provider: 100),
    )
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old " * 2000},   # ~8k chars, over window
        {"role": "user", "content": "latest"},
    ]
    bounded = loop._bounded_model_messages(messages, "anthropic")
    # The newest user turn always survives; oldest non-system turns are dropped.
    assert bounded[-1]["content"] == "latest"
    assert any("[dropped" in str(m.get("content")) for m in bounded)
    assert bounded[0]["role"] == "system"
