"""Integration tests for the NEXUS tool-execution pipeline.

These tests prove that when the model (or the user) requests a capability,
NEXUS actually EXECUTES it through the shared ``_run_tool`` pipeline, feeds the
real result back into the loop, and produces a final answer grounded in that
result. They cover web search, a normal local tool, skills, plugins, MCP tools,
Hive agent tasks (all routed through the same registry-backed pipeline), plus
failed calls, retries, timeouts, fallbacks, malformed/unsupported calls, and the
explicit-capability enforcement that synthesizes a tool call when the model only
narrates.

The model is scripted (no network) by monkeypatching ``_prompt_too_long_retry``
so each test is deterministic and fast. Fake tools are registered into the live
registry so the exact production dispatch path (schema binding -> model emits
tool_call -> parse -> execute -> feed back) is exercised.
"""

import asyncio
import json
import os
import sys
import uuid

ROOT = os.path.expanduser("~/Desktop/NEXUS AI").replace("~", os.environ.get("USERPROFILE", ""))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult  # noqa: E402
from extensions.tools.built_in.nexus_tools.registry import ToolRegistry  # noqa: E402
from nexus.main_agent import NexusLoop  # noqa: E402


# ── Fake tools (all route through the shared registry/_run_tool pipeline) ──

class FakeSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web by query."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, query="", **kwargs):
        q = str(query or "").strip()
        if not q:
            return ToolResult(success=False, error="Query required")
        return ToolResult(success=True, output=f"SEARCH_RESULTS[{q}]: https://example.com/a https://example.com/b")


class FakeReadTool(BaseTool):
    name = "test_read"
    description = "Read a local file."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, path="", **kwargs):
        return ToolResult(success=True, output=f"FILE_CONTENTS[{path}]: hello world")


class FakeSkillTool(BaseTool):
    name = "test_skill"
    description = "A skill-style capability."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, task="", **kwargs):
        return ToolResult(success=True, output=f"SKILL_DID[{task}]")


class FakePluginTool(BaseTool):
    name = "test_plugin"
    description = "A plugin capability."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, action="", **kwargs):
        return ToolResult(success=True, output=f"PLUGIN_RAN[{action}]")


class FakeMcpTool(BaseTool):
    name = "test_mcp"
    description = "An MCP server capability."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, method="", **kwargs):
        return ToolResult(success=True, output=f"MCP_CALL[{method}]")


class FakeHiveTool(BaseTool):
    name = "test_hive"
    description = "A Hive agent task capability."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, objective="", **kwargs):
        return ToolResult(success=True, output=f"HIVE_AGENT_RESULT[{objective}]")


class FlakyTool(BaseTool):
    """Fails the first N calls, then succeeds — exercises retry/fallback."""
    name = "test_flaky"
    description = "A tool that fails first then succeeds."
    def __init__(self):
        self.attempts = 0
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return True
    async def execute(self, value="", **kwargs):
        self.attempts += 1
        if self.attempts < 2:
            return ToolResult(success=False, error=f"transient failure #{self.attempts}")
        return ToolResult(success=True, output=f"FLAKY_OK[{value}]")


class TimeoutTool(BaseTool):
    name = "test_timeout"
    description = "A tool that hangs beyond the dispatch timeout."
    def is_read_only(self, params=None):
        return True
    def is_concurrency_safe(self):
        return False
    async def execute(self, seconds=0, **kwargs):
        await asyncio.sleep(float(seconds or 30))
        return ToolResult(success=True, output="should not reach here")


def make_schema(name, description, category="built_in"):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
        },
        "category": category,
    }


def register_fakes(loop):
    reg = loop.tool_registry
    reg.register_entry("web_search", make_schema("web_search", "Search the web by query."), FakeSearchTool(), replace=True)
    reg.register_entry("test_read", make_schema("test_read", "Read a file."), FakeReadTool(), replace=True)
    reg.register_entry("test_skill", make_schema("test_skill", "Skill capability."), FakeSkillTool(), replace=True)
    reg.register_entry("test_plugin", make_schema("test_plugin", "Plugin capability."), FakePluginTool(), replace=True)
    reg.register_entry("test_mcp", make_schema("test_mcp", "MCP capability."), FakeMcpTool(), replace=True)
    reg.register_entry("test_hive", make_schema("test_hive", "Hive capability."), FakeHiveTool(), replace=True)
    reg.register_entry("test_flaky", make_schema("test_flaky", "Flaky tool."), FlakyTool(), replace=True)
    reg.register_entry("test_timeout", make_schema("test_timeout", "Timeout tool."), TimeoutTool(), replace=True)
    return reg


def raw_with_tool_calls(calls):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"call_{i}", "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}), ensure_ascii=False)}}
                    for i, c in enumerate(calls)
                ],
            }
        }]
    }


def raw_with_text(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class ScriptedModel:
    """Replaces the model call. Returns queued scripted responses in order."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.calls_made = 0
    def install(self, loop):
        self.loop = loop
        async def fake_prompt_too_long_retry(messages, model_kwargs):
            self.requests.append((messages, model_kwargs))
            self.calls_made += 1
            if self.responses:
                return self.responses.pop(0)
            # Default: finalize with a short answer.
            return raw_with_text("FINAL_ANSWER based on tool results.")
        loop._prompt_too_long_retry = fake_prompt_too_long_retry
        return self


def new_loop():
    sid = "test_" + uuid.uuid4().hex[:12]
    loop = NexusLoop(root_dir=ROOT, session_id=sid)
    register_fakes(loop)
    return loop


# ── Tests ────────────────────────────────────────────────────────────────────

def test_web_search_executes_and_feeds_result():
    loop = new_loop()
    model = ScriptedModel([
        raw_with_tool_calls([{"name": "web_search", "args": {"query": "latest news"}}]),
        raw_with_text("Here is the news: SEARCH_RESULTS[latest news]"),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "Tell me the latest news", provider="deepseek", model="deepseek-chat", max_rounds=3))
    names = [a.get("name") for a in res.get("actions") or []]
    assert "web_search" in names, f"web_search not executed; actions={names}"
    assert res.get("calls_executed", 0) >= 1
    # The tool result must have been fed back into a later model request.
    fed_back = any("SEARCH_RESULTS[latest news]" in json.dumps(req[0], ensure_ascii=False)
                   for req in model.requests)
    assert fed_back, "tool result was not fed back to the model"
    assert "SEARCH_RESULTS" in (res.get("response") or ""), "final answer ignores tool result"
    print("PASS test_web_search_executes_and_feeds_result")


def test_local_tool_executes():
    loop = new_loop()
    model = ScriptedModel([
        raw_with_tool_calls([{"name": "test_read", "args": {"path": "README.md"}}]),
        raw_with_text("Read done: FILE_CONTENTS[README.md]"),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "read README.md", provider="deepseek", model="deepseek-chat", max_rounds=3))
    names = [a.get("name") for a in res.get("actions") or []]
    assert "test_read" in names, f"local tool not executed; actions={names}"
    assert any("FILE_CONTENTS[README.md]" in str(a.get("output") or "") for a in res.get("actions") or [])
    print("PASS test_local_tool_executes")


def test_skill_plugin_mcp_hive_all_use_shared_pipeline():
    # Skills, plugins, MCP and Hive all register as registry tools and are
    # dispatched through the same _run_tool pipeline. We verify each executes.
    for tool, arg in [("test_skill", {"task": "refactor"}), ("test_plugin", {"action": "deploy"}),
                     ("test_mcp", {"method": "list"}), ("test_hive", {"objective": "research"})]:
        loop = new_loop()
        ScriptedModel([
            raw_with_tool_calls([{"name": tool, "args": arg}]),
            raw_with_text("done"),
        ]).install(loop)
        res = asyncio.run(loop._run_direct_model_tool_loop(
            f"use {tool}", provider="deepseek", model="deepseek-chat", max_rounds=3))
        names = [a.get("name") for a in res.get("actions") or []]
        assert tool in names, f"{tool} not executed via shared pipeline; actions={names}"
        assert res.get("calls_executed", 0) >= 1
    print("PASS test_skill_plugin_mcp_hive_all_use_shared_pipeline")


def test_failed_call_then_retry_then_success():
    loop = new_loop()
    flaky = loop.tool_registry.get("test_flaky").instance
    ScriptedModel([
        raw_with_tool_calls([{"name": "test_flaky", "args": {"value": "x"}}]),
        raw_with_text("Recovered after retry: FLAKY_OK[x]"),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "run flaky", provider="deepseek", model="deepseek-chat", max_rounds=4))
    # The tool must have been retried (attempts >= 2) and ultimately succeeded.
    assert flaky.attempts >= 2, f"tool was not retried; attempts={flaky.attempts}"
    assert any(a.get("name") == "test_flaky" and a.get("success") for a in res.get("actions") or []), \
        "flaky tool did not ultimately succeed"
    print("PASS test_failed_call_then_retry_then_success")


def test_timeout_is_reported_not_silent():
    loop = new_loop()
    os.environ["NEXUS_TOOL_TIMEOUT"] = "1"
    try:
        ScriptedModel([
            raw_with_tool_calls([{"name": "test_timeout", "args": {"seconds": 5}}]),
            raw_with_text("done"),
        ]).install(loop)
        res = asyncio.run(loop._run_direct_model_tool_loop(
            "run timeout tool", provider="deepseek", model="deepseek-chat", max_rounds=3))
        # The slow tool must not hang the loop; it must surface a failure.
        assert res.get("calls_executed", 0) >= 1
        failed = [a for a in res.get("actions") or [] if a.get("name") == "test_timeout" and not a.get("success")]
        assert failed, "timeout tool failure was silently ignored"
    finally:
        os.environ.pop("NEXUS_TOOL_TIMEOUT", None)
    print("PASS test_timeout_is_reported_not_silent")


def test_malformed_tool_call_not_silently_ignored():
    loop = new_loop()
    # Model emits a tool that is NOT registered — must be handled, not silently
    # dropped, and the loop must continue toward a truthful outcome.
    ScriptedModel([
        raw_with_tool_calls([{"name": "nonexistent_tool", "args": {}}]),
        raw_with_text("I could not find that capability."),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "use nonexistent_tool", provider="deepseek", model="deepseek-chat", max_rounds=3))
    # The unknown tool should produce a recorded failure/error, not vanish.
    actions = res.get("actions") or []
    # Either it was recorded as a failed action or the loop reported an error.
    recorded_unknown = any(a.get("name") == "nonexistent_tool" for a in actions)
    assert recorded_unknown or res.get("error") or not res.get("success"), \
        "unsupported tool call was silently ignored"
    print("PASS test_malformed_tool_call_not_silently_ignored")


def test_capability_enforcement_synthesizes_when_model_only_narrates():
    # User explicitly says "use web search" but the model returns ONLY prose
    # (no tool_calls). The loop must synthesize and EXECUTE web_search rather
    # than accept the narration.
    loop = new_loop()
    # Model always narrates, never calls a tool.
    ScriptedModel([
        raw_with_text("Let me think... I'll just describe the news."),
        raw_with_text("Here is a briefing from SEARCH_RESULTS[latest news]."),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "Tell me today's latest news and use web search",
        provider="deepseek", model="deepseek-chat", max_rounds=4))
    names = [a.get("name") for a in res.get("actions") or []]
    assert "web_search" in names, f"capability not enforced; actions={names}"
    assert any("SEARCH_RESULTS" in str(a.get("output") or "") for a in res.get("actions") or [])
    print("PASS test_capability_enforcement_synthesizes_when_model_only_narrates")


def test_final_response_uses_tool_result():
    loop = new_loop()
    ScriptedModel([
        raw_with_tool_calls([{"name": "test_hive", "args": {"objective": "summarize"}}]),
        raw_with_text("Result was HIVE_AGENT_RESULT[summarize]. Done."),
    ]).install(loop)
    res = asyncio.run(loop._run_direct_model_tool_loop(
        "run a hive task to summarize", provider="deepseek", model="deepseek-chat", max_rounds=3))
    assert res.get("success")
    assert "HIVE_AGENT_RESULT[summarize]" in (res.get("response") or ""), \
        "final response does not incorporate the tool result"
    print("PASS test_final_response_uses_tool_result")


if __name__ == "__main__":
    test_web_search_executes_and_feeds_result()
    test_local_tool_executes()
    test_skill_plugin_mcp_hive_all_use_shared_pipeline()
    test_failed_call_then_retry_then_success()
    test_timeout_is_reported_not_silent()
    test_malformed_tool_call_not_silently_ignored()
    test_capability_enforcement_synthesizes_when_model_only_narrates()
    test_final_response_uses_tool_result()
    print("\nALL TOOL-EXECUTION PIPELINE TESTS PASSED")
