"""Regression tests for the V5 transcript-driven model/tool loop."""

import asyncio
import json
import time

from orchestrators.v5.core import NexusLoopV5, _DuckPerceived
from orchestrators.v5.events import V5EventEmitter
from nexus.run_context import load_run_context


def _native(name, args, call_id):
    return {
        "choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                             "function": {"name": name, "arguments": args}}],
        }}]
    }


def test_internal_route_and_verification_events_are_not_public():
    class Runtime:
        work_event_sink = None

    class Emitter(V5EventEmitter):
        def __init__(self):
            self.runtime = Runtime()
            self.work_event_sink = None
            self._stream_events = []
            self._current_turn_id = "turn-test"
            self.session_id = "session-test"
            self.logger = type("Logger", (), {"debug": lambda *_args: None})()

    emitter = Emitter()
    asyncio.run(emitter._emit_runtime_event(
        "planning.started", "Choosing an execution route", "running",
        event_id="planning-test", visibility="internal",
    ))
    asyncio.run(emitter._emit_runtime_event(
        "verification.completed", "Work verified", "completed",
        event_id="verification-test", visibility="internal",
    ))

    assert [event["visibility"] for event in emitter._stream_events] == ["internal", "internal"]


def test_direct_loop_replays_tool_result_to_model_without_planner(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="direct-test")
    seen = []
    replies = iter([
        _native("fixture_tool", '{"value": 3}', "call-1"),
        {"choices": [{"message": {"content": "The tool returned 6."}}]},
    ])

    async def model(messages, **kwargs):
        seen.append(messages)
        return next(replies)

    async def tool(call):
        assert call.name == "fixture_tool"
        assert call.params == {"value": 3}
        return "6"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [{"type": "function", "function": {"name": "fixture_tool"}}]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("say the result"))

    assert result["success"] is True
    assert result["response"] == "The tool returned 6."
    assert result["calls_executed"] == 1
    assert seen[1][-2]["role"] == "assistant"
    assert seen[1][-2]["tool_calls"][0]["function"]["name"] == "fixture_tool"
    assert seen[1][-1] == {
        "role": "tool", "name": "fixture_tool", "tool_call_id": "call-1", "content": "6"
    }


def test_direct_loop_executes_tools_when_a_run_deadline_is_active(tmp_path):
    """Deadline enforcement must not break every model-selected tool call."""
    loop = NexusLoopV5(str(tmp_path), session_id="deadline-tool-test")
    replies = iter([
        _native("fixture_tool", "{}", "call-deadline"),
        {"choices": [{"message": {"content": "The tool completed."}}]},
    ])

    async def model(_messages, **_kwargs):
        return next(replies)

    async def tool(_call):
        return "verified output"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **_kwargs: []
    loop._run_tool = tool
    loop._current_turn_id = "turn-deadline-tool-test"
    loop._run_controls.register(
        loop._current_turn_id,
        deadline_at=time.monotonic() + 5,
    )

    result = asyncio.run(loop._run_direct_model_tool_loop("run the tool"))

    assert result["success"] is True
    assert result["calls_executed"] == 1
    assert result["actions"][0]["output"] == "verified output"


def test_direct_loop_is_bounded_and_does_not_call_planner(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="bound-test")
    calls = 0

    async def model(messages, **kwargs):
        nonlocal calls
        calls += 1
        return _native("fixture_tool", "{}", f"call-{calls}")

    async def tool(call):
        return "ok"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("unrelated wording", max_rounds=2))

    assert result["success"] is False
    assert result["tool_rounds"] == 2
    assert result["calls_executed"] == 2
    # The tool budget is two rounds plus one reserved provider finalization
    # turn. A provider that keeps requesting tools is still bounded.
    assert calls == 3


def test_direct_loop_records_real_tool_evidence_and_does_not_parse_text(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="evidence-test")
    replies = iter([
        {"choices": [{"message": {"content": "fixture_tool({\"value\": 3})"}}]},
    ])

    async def model(messages, **kwargs):
        return next(replies)

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop._run_direct_model_tool_loop("do it", max_rounds=1))

    assert result["success"] is True
    assert result["calls_executed"] == 0
    assert result["actions"] == []


def test_direct_loop_reports_success_for_ordinary_conversation(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="hello-test")

    async def model(messages, **kwargs):
        return {"choices": [{"message": {"content": "Hello!"}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop._run_direct_model_tool_loop("hello"))

    assert result["response"] == "Hello!"
    assert result["success"] is True
    assert result["calls_executed"] == 0
    assert result["verification"]["mode"] == "conversation"
    assert result["verification"]["evidence_ok"] is True


def test_direct_loop_accepts_model_driven_repair_after_failed_tool(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="repair-loop-test")
    rounds = 0
    seen_messages = []

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        seen_messages.append(list(messages))
        if rounds == 1:
            return _native("terminal", {"command": "bad"}, "first")
        if rounds == 2:
            return _native("terminal", {"command": "fixed"}, "second")
        return {"choices": [{"message": {"content": "The command was repaired and verified."}}]}

    async def tool(call):
        if call.params.get("command") == "bad":
            raise RuntimeError("command failed")
        return "fixed output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("fix the command", max_rounds=4))

    assert result["success"] is True
    assert result["verification"]["success"] is True
    assert result["verification"]["failed_actions"] == 0
    assert result["actions"][0]["repaired"] is True
    assert any("REPAIR REQUIRED" in str(item.get("content")) for item in seen_messages[1])


def test_direct_loop_allows_repair_after_last_tool_round(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="boundary-repair-loop-test")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            return _native("terminal", {"command": "bad"}, "bad-call")
        if rounds == 2:
            return _native("terminal", {"command": "fixed"}, "fixed-call")
        return {"choices": [{"message": {"content": "The repaired command is verified."}}]}

    async def tool(call):
        if call.params.get("command") == "bad":
            raise RuntimeError("sandbox rejected command")
        return "verified output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("repair the command", max_rounds=1))

    assert result["success"] is True
    assert result["calls_executed"] == 2
    assert result["actions"][0]["repaired"] is True


def test_same_model_response_cannot_repair_an_unobserved_failure(tmp_path):
    """Two calls in one response are not a retry until the model sees results."""
    loop = NexusLoopV5(str(tmp_path), session_id="same-response-repair-test")
    rounds = 0
    executed = []

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [
                    {"id": "bad", "type": "function", "function": {"name": "terminal", "arguments": '{"command":"bad"}'}},
                    {"id": "good", "type": "function", "function": {"name": "terminal", "arguments": '{"command":"good"}'}},
                ],
            }}]}
        return {"choices": [{"message": {"content": "The run is complete."}}]}

    async def tool(call):
        executed.append(call.params.get("command"))
        if call.params.get("command") == "bad":
            raise RuntimeError("command failed")
        return "good output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("run both", max_rounds=3))

    assert result["success"] is False
    assert result["verification"]["failed_actions"] == 1
    assert result["actions"][0].get("repaired") is not True
    assert executed == ["bad"]


def test_text_tool_calls_get_unique_ids_across_a_batch(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="text-tool-id-test")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            return {"choices": [{"message": {
                "content": '<function=terminal>{"command":"one"}\n<function=terminal>{"command":"two"}'
            }}]}
        return {"choices": [{"message": {"content": "Both commands completed."}}]}

    async def tool(call):
        return f"output for {call.params['command']}"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("run both", max_rounds=3))

    assert result["success"] is True
    assert result["calls_executed"] == 2
    ids = [item["call_id"] for item in result["actions"]]
    assert len(ids) == len(set(ids))
    assistant = next(item for item in result["messages"] if item.get("role") == "assistant")
    assert [item["id"] for item in assistant["tool_calls"]] == ids


def test_provider_error_text_is_not_a_successful_conversation(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="provider-error-text-test")

    async def model(messages, **kwargs):
        return {"choices": [{"message": {"content": "Error: LM Studio returned 500"}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop._run_direct_model_tool_loop("hello", max_rounds=1))

    assert result["success"] is False
    assert result["verification"]["evidence_ok"] is False
    assert result["error"] == "provider failure returned no usable model response"


def test_provider_error_retries_with_clean_current_turn_transcript(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="provider-history-recovery-test")
    seen = []

    async def model(messages, **kwargs):
        seen.append(messages)
        if len(seen) == 1:
            return {"choices": [{"message": {"content": "Error: DeepSeek API returned status 400"}}]}
        return {"choices": [{"message": {"content": "Recovered response"}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": f"tool_{i}", "parameters": {"type": "object"}}}
        for i in range(min(int(kwargs.get("top_k") or 25), 25))
    ]

    result = asyncio.run(loop._run_direct_model_tool_loop(
        "continue safely", conversation_history=[
            {"role": "user", "content": "old request"},
            {"role": "assistant", "content": "old tool envelope", "tool_calls": [{"id": "orphan"}]},
        ], max_rounds=2,
    ))

    assert result["success"] is True
    assert len(seen) == 2
    assert [item["role"] for item in seen[1]] == ["system", "user"]
    assert seen[1][-1]["content"] == "continue safely"


def test_direct_loop_bounds_repeated_non_unavailable_failures(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="repair-budget-test")
    calls = 0

    async def model(messages, **kwargs):
        return _native("terminal", {"command": "always-bad"}, f"call-{len(messages)}")

    async def tool(call):
        nonlocal calls
        calls += 1
        raise RuntimeError("compiler failed")

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("keep trying", max_rounds=8))

    assert result["success"] is False
    assert calls == loop.repair_attempt_budget
    assert result["error"] == "repair attempts exhausted"
    assert result["verification"]["failed_actions"] == loop.repair_attempt_budget


def test_direct_loop_redacts_secret_from_failed_tool_observation(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="tool-error-redaction")
    secret = "sk-live-direct-loop-secret"

    async def model(messages, **kwargs):
        return _native("terminal", {"command": "always-bad"}, "call-1")

    async def tool(call):
        raise RuntimeError(f"remote failed with token={secret}")

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("run the tool", max_rounds=2))

    assert result["success"] is False
    assert secret not in json.dumps(result, default=str)
    assert "REDACTED" in json.dumps(result, default=str)


def test_direct_loop_redacts_secret_from_successful_tool_output_and_evidence(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="tool-output-redaction")
    secret = "sk-live-success-output-secret"
    seen_messages = []
    replies = iter([
        _native("fixture_tool", "{}", "call-1"),
        {"choices": [{"message": {"content": "The check completed."}}]},
    ])

    async def model(messages, **kwargs):
        seen_messages.append(messages)
        return next(replies)

    async def tool(call):
        return f"verified output with token={secret}"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("do the check", max_rounds=2))

    serialized = json.dumps(result, default=str)
    assert result["success"] is True
    assert secret not in serialized
    assert "REDACTED" in serialized
    assert secret not in json.dumps(seen_messages, default=str)


def test_active_hive_self_repair_gets_one_escalation_after_native_budget(tmp_path, monkeypatch):
    """Hive adds one reviewed decision after native repair is exhausted."""
    monkeypatch.setenv("NEXUS_HIVE", "1")
    monkeypatch.setenv("NEXUS_V5_ACTIVE_MODE", "true")
    loop = NexusLoopV5(str(tmp_path), session_id="hive-repair-escalation")
    loop.repair_attempt_budget = 1
    calls = {"count": 0}
    hive_calls = []

    async def model(_messages, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _native("terminal", {"command": "first"}, "first")
        if calls["count"] == 2:
            return _native("terminal", {"command": "corrected"}, "corrected")
        return {"choices": [{"message": {"content": "Corrected successfully."}}]}

    async def tool(call):
        if call.params.get("command") == "first":
            raise RuntimeError("first attempt failed")
        return "fresh verified output"

    async def hive_repair(result, perceived):
        hive_calls.append((result["actions"][-1]["tool"], perceived.original_input))
        return [{"description": "retry with corrected command", "tool": "terminal", "params": {}}]

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **_kwargs: []
    loop._run_tool = tool
    loop._hive_self_repair = hive_repair

    result = asyncio.run(loop._run_direct_model_tool_loop("repair the command", max_rounds=4))

    assert result["success"] is True
    assert hive_calls == [("terminal", "repair the command")]
    assert any(
        message.get("role") == "system"
        and "HIVE REPAIR PROPOSAL" in message.get("content", "")
        for message in result["messages"]
    )


def test_direct_loop_only_marks_immediately_previous_failure_repaired(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="repair-attribution-test")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds <= 2:
            return _native("terminal", {"command": f"bad-{rounds}"}, str(rounds))
        if rounds == 3:
            return _native("terminal", {"command": "fixed"}, "3")
        return {"choices": [{"message": {"content": "Still incomplete."}}]}

    async def tool(call):
        if call.params.get("command") != "fixed":
            raise RuntimeError("command failed")
        return "fixed output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("repair twice", max_rounds=4))

    assert result["success"] is False
    assert result["actions"][0].get("repaired") is not True
    assert result["actions"][1].get("repaired") is True


def test_turn_persists_terminal_run_context_for_restart_resume(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="durable-session")

    async def model(messages, **kwargs):
        return {"choices": [{"message": {"content": "Hello, sir."}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop.run("hello"))
    context = load_run_context(
        str(tmp_path), "durable-session", result["turn_id"]
    )

    assert result["success"] is True
    assert context["status"] == "completed"
    assert context["terminal_event"] == "run.completed"
    assert context["prompt_preview"] == "hello"


def test_direct_loop_does_not_leak_raw_tool_envelope(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="protocol-test")

    async def model(messages, **kwargs):
        return {"choices": [{"message": {"content": "<function=gui-tester>{}"}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop._run_direct_model_tool_loop("inspect the GUI", max_rounds=1))

    assert result["success"] is False
    assert "<function=" not in result["response"]
    assert result["error"] == "repair attempts exhausted"


def test_direct_loop_reserves_finalization_after_last_tool_round(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="finalization-boundary-test")
    replies = iter([
        _native("fixture_tool", "{}", "call-1"),
        {"choices": [{"message": {"content": "The requested check completed."}}]},
    ])

    async def model(messages, **kwargs):
        return next(replies)

    async def tool(call):
        return "real tool result"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("do the check", max_rounds=1))

    assert result["success"] is True
    assert result["response"] == "The requested check completed."
    assert result["calls_executed"] == 1


def test_direct_loop_stops_repeated_unavailable_tool_retries(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="unavailable-tool-test")
    calls = 0

    async def model(messages, **kwargs):
        nonlocal calls
        calls += 1
        return _native("missing_tool", "{}", f"call-{calls}")

    async def tool(call):
        raise RuntimeError("Error: Tool 'missing_tool' not found. Available: ['reading']")

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("use the missing tool", max_rounds=8))

    assert result["success"] is False
    assert calls == 2
    assert len(result["actions"]) == 2
    assert "unavailable tool" in result["response"]
    assert "<function=" not in result["response"]


def test_direct_schemas_preserve_top_level_required_fields(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="schema-test")

    class Entry:
        schema = {
            "description": "MCP lookup",
            "params": {"query": {"type": "string"}},
            "required": ["query"],
        }

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"mcp_lookup": {}}

        def get(self, name):
            return Entry()

    loop.tool_registry = Registry()
    schemas = loop._get_direct_tool_schemas()

    assert schemas[0]["function"]["parameters"]["required"] == ["query"]


def test_direct_schemas_include_complete_registry_by_default(tmp_path, monkeypatch):
    loop = NexusLoopV5(str(tmp_path), session_id="schema-complete-test")

    class Entry:
        schema = {"description": "test", "params": {}}

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"tool_b": {}, "tool_a": {}, "tool_c": {}}

        def get(self, name):
            return Entry()

    monkeypatch.delenv("NEXUS_TOOL_SCHEMA_LIMIT", raising=False)
    loop.tool_registry = Registry()
    schemas = loop._get_direct_tool_schemas()

    assert [item["function"]["name"] for item in schemas] == ["tool_a", "tool_b", "tool_c"]


def test_prompt_only_skills_are_not_advertised_as_executable_tools(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="skill-tool-boundary-test")

    class Entry:
        def __init__(self, schema):
            self.schema = schema

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"claude-code": {}, "terminal": {}}

        def get(self, name):
            if name == "claude-code":
                return Entry({"category": "skill", "description": "Prompt guidance"})
            return Entry({"category": "system", "description": "Execute a command", "params": {}})

    loop.tool_registry = Registry()
    names = [item["function"]["name"] for item in loop._get_direct_tool_schemas(query="execute a command")]
    assert "claude-code" not in names
    assert "terminal" in names


def test_current_news_query_keeps_web_search_in_full_tool_catalogue(tmp_path, monkeypatch):
    loop = NexusLoopV5(str(tmp_path), session_id="news-schema-ranking-test")

    class Entry:
        def __init__(self, name):
            self.schema = {
                "description": "Search the web by query" if name == "web_search" else "Unrelated action",
                "params": {"query": {"type": "string"}} if name == "web_search" else {},
            }

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"web_search": {}, "unrelated_action": {}}

        def get(self, name):
            return Entry(name)

    monkeypatch.delenv("NEXUS_TOOL_SCHEMA_LIMIT", raising=False)
    loop.tool_registry = Registry()
    names = [
        item["function"]["name"]
        for item in loop._get_direct_tool_schemas(query="tell me today's news", provider="lm_studio")
    ]

    assert names == ["unrelated_action", "web_search"]


def test_schema_catalogue_is_not_query_ranked(tmp_path, monkeypatch):
    loop = NexusLoopV5(str(tmp_path), session_id="local-schema-budget-test")

    class Entry:
        def __init__(self, description):
            self.schema = {"description": description, "params": {}}

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"irrelevant_%02d" % i: {} for i in range(30)} | {"reading": {}}

        def get(self, name):
            return Entry("Read files from the workspace") if name == "reading" else Entry("Unrelated action")

    monkeypatch.delenv("NEXUS_TOOL_SCHEMA_LIMIT", raising=False)
    loop.tool_registry = Registry()
    schemas = loop._get_direct_tool_schemas(query="read README.md", provider="lm_studio")

    assert len(schemas) == 31
    assert schemas[-1]["function"]["name"] == "reading"


def test_local_ordinary_chat_uses_the_full_tool_catalogue(tmp_path, monkeypatch):
    loop = NexusLoopV5(str(tmp_path), session_id="local-chat-schema-test")

    class Entry:
        schema = {"description": "Run an unrelated action", "params": {}}

    class Registry:
        def list_tools(self, include_unavailable=False):
            return {"unrelated_action": {}}

        def get(self, name):
            return Entry()

    monkeypatch.delenv("NEXUS_TOOL_SCHEMA_LIMIT", raising=False)
    loop.tool_registry = Registry()
    assert [item["function"]["name"] for item in loop._get_direct_tool_schemas(query="hello", provider="lm_studio")] == [
        "unrelated_action"
    ]


def test_local_model_request_is_compacted_without_deleting_durable_transcript(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="local-context-budget-test")
    messages = [
        {"role": "system", "content": "system instructions"},
        *({"role": "user", "content": "old context " + ("x" * 800)} for _ in range(20)),
        {"role": "user", "content": "latest request"},
    ]

    bounded = loop._bounded_model_messages(messages, "lm_studio")

    assert bounded[0]["role"] == "system"
    assert bounded[-1]["content"] == "latest request"
    assert sum(len(str(item.get("content") or "")) for item in bounded) < 7000
    assert len(messages) == 22


def test_raw_model_request_omits_unset_optional_fields(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="raw-request-null-test")
    seen = {}

    class Brain:
        def generate(self, **kwargs):
            seen.update(kwargs)
            return "Hello"

    loop.kernel._instances["moe"] = Brain()
    result = loop._call_model_raw([{"role": "user", "content": "hello"}], max_tokens=None, tools=None)

    assert result == "Hello"
    assert "max_tokens" not in seen
    assert "tools" not in seen


def test_direct_tool_decision_and_observation_are_persisted_before_final_answer(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="durable-tool-turn")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            return _native("fixture_tool", '{"value": 4}', "persist-call")
        return {"choices": [{"message": {"content": "Verified 8."}}]}

    async def tool(call):
        return "8"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []
    loop._run_tool = tool
    loop._current_turn_id = "durable-tool-turn-id"

    result = asyncio.run(loop._run_direct_model_tool_loop("calculate it", max_rounds=2))
    transcript = loop.runtime.memory

    assert result["success"] is True
    assert any(item.get("kind") == "tool_call" for item in transcript)
    assert any(item.get("kind") == "tool_result" and item.get("tool_call_id") == "persist-call" for item in transcript)


def test_resume_marks_orphaned_tool_call_unknown_without_replaying_it(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="orphan-resume-test")
    seen = []

    async def model(messages, **_kwargs):
        seen.extend(messages)
        return {"choices": [{"message": {"content": "I will inspect the state first."}}]}

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **kwargs: []

    result = asyncio.run(loop._run_direct_model_tool_loop(
        "continue the task", max_rounds=1,
        conversation_history=[
            {"role": "user", "content": "create the file", "turn_id": "old"},
            {"role": "assistant", "content": "", "turn_id": "old", "tool_calls": [
                {"id": "orphan-1", "type": "function", "function": {
                    "name": "creating", "arguments": '{"path":"x.txt"}'
                }}
            ]},
        ],
    ))

    assert result["success"] is True
    unknown = [m for m in seen if m.get("tool_call_id") == "orphan-1"]
    assert len(unknown) == 1
    assert unknown[0]["role"] == "tool"
    assert unknown[0]["content"].startswith("UNKNOWN:")


def test_live_turn_always_uses_direct_loop(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="live-dispatch-test")
    seen = []

    async def direct(task_desc, **kwargs):
        seen.append(task_desc)
        return {"success": False, "response": "Hello!", "actions": [], "calls_executed": 0}

    loop._run_direct_model_tool_loop = direct
    async def no_meta_learning():
        return None

    loop._meta_learning_optimize = no_meta_learning
    async def perception(turn):
        return _DuckPerceived(turn.user_input, turn.input_type)

    loop._perceive_input = perception
    loop._decide_planning = lambda *_args, **_kwargs: asyncio.sleep(0)
    loop._inject_hive_context = lambda *_args, **_kwargs: asyncio.sleep(0)

    result = asyncio.run(loop.run("hello"))

    assert result["response"] == "Hello!"
    assert result["success"] is False
    assert result["state"] == "failed"
    assert seen == ["hello"]


def test_live_turn_uses_model_route_before_direct_tool_loop(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="route-dispatch-test")
    observed = {}

    async def route_model(_messages, **_kwargs):
        return '{"mode":"PLAN","tool":"mixed","hive":true,"mcp":false,"model":"strong"}'

    async def perception(turn):
        return _DuckPerceived(turn.user_input, turn.input_type)

    async def hive(_perceived):
        observed["hive_called"] = True

    async def direct(_task_desc, **_kwargs):
        observed["planning"] = loop.runtime.feature_planning
        observed["hive"] = loop.runtime.feature_hive
        return {"success": True, "response": "completed", "actions": [], "calls_executed": 0}

    loop._safe_model_call = route_model
    loop._perceive_input = perception
    loop._inject_hive_context = hive
    loop._run_direct_model_tool_loop = direct

    result = asyncio.run(loop.run("build a small website"))

    assert result["success"] is True
    assert observed == {"hive_called": True, "planning": True, "hive": True}


def test_stream_turn_persists_transcript_for_refresh_and_resume(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="resume-session")

    async def no_meta_learning():
        return None

    async def direct(task_desc, **kwargs):
        return {"success": False, "response": "Hello from the persisted turn.", "actions": [], "calls_executed": 0}

    loop._meta_learning_optimize = no_meta_learning
    loop._run_direct_model_tool_loop = direct

    async def collect():
        return [event async for event in loop._turn_events("hello", turn_id="turn-resume-1")]

    events = asyncio.run(collect())
    transcript_path = tmp_path / "logs" / "sessions" / "resume-session.json"
    transcript = __import__("json").loads(transcript_path.read_text(encoding="utf-8"))

    assert [message["role"] for message in transcript] == ["user", "assistant"]
    assert transcript[0]["content"] == "hello"
    assert transcript[0]["turn_id"] == "turn-resume-1"
    assert transcript[1]["content"] == "Hello from the persisted turn."
    assert transcript[1]["turn_id"] == "turn-resume-1"
    assert events[-1]["type"] == "done"


def test_stream_turn_transcript_write_is_idempotent(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="idempotent-session")
    loop._persist_turn_message("user", "same prompt", "turn-1")
    loop._persist_turn_message("user", "same prompt", "turn-1")
    loop._persist_turn_message("assistant", "same answer", "turn-1")
    loop._persist_turn_message("assistant", "updated answer", "turn-1")

    transcript_path = tmp_path / "logs" / "sessions" / "idempotent-session.json"
    transcript = __import__("json").loads(transcript_path.read_text(encoding="utf-8"))
    assert transcript == [
        {"role": "user", "content": "same prompt", "turn_id": "turn-1"},
        {"role": "assistant", "content": "updated answer", "turn_id": "turn-1"},
    ]


def test_direct_loop_stops_when_identical_tool_call_repeats_without_progress(tmp_path):
    """Closed loop-detection: an identical (tool, params) call that keeps
    returning the same result must terminate the turn instead of burning the
    whole round budget on a non-progressing strategy."""
    loop = NexusLoopV5(str(tmp_path), session_id="stagnation-test")
    model_calls = {"n": 0}
    tool_calls = {"n": 0}

    async def model(messages, **kwargs):
        model_calls["n"] += 1
        # A stuck model: always asks for the exact same call with the exact
        # same arguments, no matter what the observation was.
        return _native("stuck_tool", '{"q": "same"}', f"call-{model_calls['n']}")

    async def tool(call):
        tool_calls["n"] += 1
        return "identical result"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": "stuck_tool"}}
    ]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("do the stuck thing"))

    assert result["success"] is False
    assert result["error"] == "repeated identical tool call made no progress"
    assert result["stagnation"]["tool"] == "stuck_tool"
    assert result["stagnation"]["repeats"] == loop.repeat_call_budget
    # It must stop AT the budget, not run the full round budget.
    assert tool_calls["n"] == loop.repeat_call_budget
    assert tool_calls["n"] < loop.direct_loop_max_rounds
    # Every assistant tool_call still has a matching tool result: the
    # transcript we persisted must remain a valid provider envelope.
    ids = [c["id"] for m in result["messages"]
           if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])]
    results = [m["tool_call_id"] for m in result["messages"] if m.get("role") == "tool"]
    assert ids == results


def test_direct_loop_allows_same_tool_with_different_arguments(tmp_path):
    """Loop detection must key on (tool, params), not the tool name alone."""
    loop = NexusLoopV5(str(tmp_path), session_id="stagnation-neg")
    n = {"i": 0}

    async def model(messages, **kwargs):
        n["i"] += 1
        if n["i"] <= 3:
            return _native("probe", '{"q": "%d"}' % n["i"], f"call-{n['i']}")
        return {"choices": [{"message": {"content": "Explored three paths."}}]}

    async def tool(call):
        return "result for " + str(call.params.get("q"))

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": "probe"}}
    ]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("probe three ways"))

    assert result["success"] is True
    assert "stagnation" not in result
    assert result["calls_executed"] == 3


def _native_multi(names, cid):
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": f"{cid}-{i}", "type": "function",
         "function": {"name": n, "arguments": '{"q":"same"}'}}
        for i, n in enumerate(names)]}}]}


def test_stagnation_stop_still_answers_every_tool_call_in_the_batch(tmp_path):
    """A stagnation stop mid-batch must not leave an assistant tool_call
    without a matching tool result: OpenAI-compatible providers reject that
    envelope, so the next request (or a resume) would fail outright."""
    loop = NexusLoopV5(str(tmp_path), session_id="envelope-test")
    n = {"i": 0}

    async def model(messages, **kwargs):
        n["i"] += 1
        return _native_multi(["stuck_tool", "second_tool"], f"c{n['i']}")

    async def tool(call):
        return "identical result"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": "stuck_tool"}},
        {"type": "function", "function": {"name": "second_tool"}},
    ]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("go"))

    assert result["error"] == "repeated identical tool call made no progress"
    ids = [c["id"] for m in result["messages"]
           if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])]
    results = [m["tool_call_id"] for m in result["messages"] if m.get("role") == "tool"]
    assert ids, "expected tool calls in the transcript"
    assert [i for i in ids if i not in results] == [], (
        "every assistant tool_call must have a matching tool result"
    )


def test_polling_workflow_is_not_mistaken_for_stagnation(tmp_path):
    """A poll/wait-until-ready workflow issues the SAME call repeatedly and
    that is real progress: the observation changes. Loop detection must key
    on (tool, params, observation), so polling is never falsely stopped."""
    loop = NexusLoopV5(str(tmp_path), session_id="polling-test")
    state = {"n": 0}

    async def model(messages, **kwargs):
        state["n"] += 1
        if state["n"] <= 5:
            return _native("check_status", '{"job": "build"}', f"poll-{state['n']}")
        return {"choices": [{"message": {"content": "The job finished."}}]}

    async def tool(call):
        # Same request, genuinely advancing observation.
        return f"progress {state['n']}0%"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": "check_status"}}
    ]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("poll until done"))

    assert result["success"] is True
    assert "stagnation" not in result
    assert result["calls_executed"] == 5




def test_stagnation_persists_valid_envelope_after_mid_batch_stop(tmp_path):
    """Stagnation tripping on slot k<N-1 must leave the *persisted* transcript
    (runtime.memory, the resume/continue source) with a valid envelope: every
    assistant tool_call id has a matching tool_result entry. A missing result
    on disk makes the next request/resume 400, so this is the sticky failure
    the reviewer was worried about."""
    loop = NexusLoopV5(str(tmp_path), session_id="persist-envelope")
    n = {"i": 0}

    async def model(messages, **kwargs):
        n["i"] += 1
        return _native_multi(["stuck_tool", "second_tool"], f"c{n['i']}")

    async def tool(call):
        return "identical result"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **kwargs: [
        {"type": "function", "function": {"name": "stuck_tool"}},
        {"type": "function", "function": {"name": "second_tool"}},
    ]
    loop._run_tool = tool

    result = asyncio.run(loop._run_direct_model_tool_loop("go"))
    assert result["error"] == "repeated identical tool call made no progress"

    # The returned transcript is what production persists (via the session
    # bus / checkpoint resume) and what the next request sends. Every
    # assistant tool_call id must have a matching tool result -- including
    # the skipped results the detector appends for the remainder of the
    # batch. A missing result makes the next request/resume 400.
    messages = result["messages"]
    call_ids = []
    result_ids = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant":
            for c in (m.get("tool_calls") or []):
                call_ids.append(str(c.get("id") or c.get("call_id") or ""))
        if m.get("role") == "tool":
            result_ids.append(str(m.get("tool_call_id") or ""))
    assert call_ids, "assistant tool calls must be present in the transcript"
    missing = [i for i in call_ids if i and i not in result_ids]
    assert missing == [], f"tool calls without a matching result: {missing}"
    # The second tool in the batch was never executed, so it must appear as
    # an explicit skipped tool result rather than being absent.
    assert any(
        "Skipped" in (m.get("content") or "") for m in messages if m.get("role") == "tool"
    ), "remaining batch calls must be recorded as skipped results"

def test_active_hive_stall_replan_is_connected_to_live_loop(tmp_path, monkeypatch):
    """The live loop records actions and exposes one Hive replan proposal."""
    monkeypatch.setenv("NEXUS_HIVE", "1")
    monkeypatch.setenv("NEXUS_V5_ACTIVE_MODE", "true")
    loop = NexusLoopV5(str(tmp_path), session_id="hive-replan-live")
    loop.repeat_call_budget = 10
    model_calls = {"count": 0}
    replan_calls = []

    async def model(_messages, **_kwargs):
        model_calls["count"] += 1
        if model_calls["count"] >= 5:
            return {"choices": [{"message": {"content": "Finished after replan."}}]}
        return _native("probe", "{}", f"replan-{model_calls['count']}")

    async def tool(_call):
        return "same observation"

    async def replan(perceived):
        replan_calls.append(perceived.original_input)
        if len(loop._ledger_history()) >= 3:
            return [{"description": "Use the alternate probe", "tool": "reading"}]
        return None

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **_kwargs: [
        {"type": "function", "function": {"name": "probe"}}
    ]
    loop._run_tool = tool
    loop._hive_replan_on_stall = replan

    result = asyncio.run(loop._run_direct_model_tool_loop("recover the stalled task"))

    assert result["success"] is True
    assert replan_calls == [
        "recover the stalled task",
        "recover the stalled task",
        "recover the stalled task",
        "recover the stalled task",
    ]
    assert len(loop._ledger_history()) == result["calls_executed"]
    assert any(
        message.get("role") == "system"
        and "HIVE REPLAN PROPOSAL" in message.get("content", "")
        for message in result["messages"]
    )


def test_chaos_repeated_identical_success_triggers_stagnation(tmp_path):
    """CHAOS: a tool that keeps succeeding with the SAME result (e.g. a
    poll/wait-until-ready that never advances) must be detected as
    stagnation and stopped, not looped forever or reported as real
    progress. This exercises the closed loop-detection path end-to-end
    through the real runtime loop."""
    loop = NexusLoopV5(str(tmp_path), session_id="stagnation-chaos")
    # Model keeps asking for the same tool call; tool keeps returning the
    # identical observation. This is the harder case the detector owns.
    replies = iter([
        _native("fixture_tool", '{"path": "/job/1"}', "call-1"),
        _native("fixture_tool", '{"path": "/job/1"}', "call-2"),
        _native("fixture_tool", '{"path": "/job/1"}', "call-3"),
        _native("fixture_tool", '{"path": "/job/1"}', "call-4"),
        _native("fixture_tool", '{"path": "/job/1"}', "call-5"),
        {"choices": [{"message": {"content": "done"}}]},
    ])

    async def model(_messages, **_kwargs):
        return next(replies)

    async def tool(call):
        # Always reports the same unchanged status.
        return "job still pending"

    loop._safe_model_call_raw = model
    loop._get_tool_schemas = lambda **_kwargs: [{"type": "function", "function": {"name": "fixture_tool"}}]
    loop._run_tool = tool
    loop._current_turn_id = "turn-stagnation-chaos"

    result = asyncio.run(loop._run_direct_model_tool_loop("check the job", max_rounds=20))

    # Must NOT loop until max_rounds; must detect stagnation and stop.
    assert result.get("stagnation") is not None, "stagnation not detected under repeated identical success"
    assert result["success"] is False, "stagnation must not be reported as success"
    # The repair/loop budget (not max_rounds) bounds it.
    assert result["tool_rounds"] < 20, "loop was not bounded by stagnation detector"
    assert "made no progress" in (result.get("error") or "")
