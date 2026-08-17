"""Capabilities hardening: env-tunable registry default retry policy.

The registry keeps its legacy behavior (no retry) when no env is set, but
operators can opt every tool into retries via NEXUS_TOOL_DEFAULT_MAX_RETRIES.
Side-effecting tools must still refuse retries unless the schema opts in.
"""

import asyncio

import pytest

from extensions.tools.built_in.nexus_tools.base_tool import ToolResult
from extensions.tools.built_in.nexus_tools.registry import ToolEntry, ToolRegistry
import extensions.tools.built_in.nexus_tools.registry as registry_mod


class _FlakyTool:
    def __init__(self, failures=1):
        self.calls = 0
        self.failures = failures

    async def execute(self, **_params):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("transient transport failure")
        return ToolResult(success=True, output="ok")


def _registry(name, schema, tool):
    registry = object.__new__(ToolRegistry)
    registry.root = ""
    registry._tools = {name: ToolEntry(name, schema, tool)}
    return registry


def test_default_retry_policy_is_no_retry_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", raising=False)
    tool = _FlakyTool(failures=3)
    registry = _registry("search_default", {"params": {}}, tool)

    result = asyncio.run(registry.execute("search_default"))

    assert result.success is False
    assert tool.calls == 1


def test_env_default_max_retries_retries_with_backoff(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "2")
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_BASE", "0")
    tool = _FlakyTool(failures=2)
    registry = _registry("search_env", {"params": {}}, tool)

    result = asyncio.run(registry.execute("search_env"))

    assert result.success is True
    assert tool.calls == 3, "expected 1 initial attempt + 2 retries"


def test_env_retry_backoff_progression(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "2")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    tool = _FlakyTool(failures=2)
    registry = _registry("search_backoff", {"params": {}}, tool)

    result = asyncio.run(registry.execute("search_backoff"))

    assert result.success is True
    # Default NEXUS_TOOL_RETRY_BACKOFF_BASE=0.5s doubles after each failure.
    assert sleeps == [0.5, 1.0]


def test_env_retry_backoff_cap_applies(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "4")
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_BASE", "0.5")
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_MAX", "1")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    tool = _FlakyTool(failures=4)
    registry = _registry("search_capped", {"params": {}}, tool)

    result = asyncio.run(registry.execute("search_capped"))

    assert result.success is True
    # 4 failures → 4 sleeps, capped at the 1s env ceiling after doubling once.
    assert sleeps == [0.5, 1.0, 1.0, 1.0], "backoff must not exceed the env cap"


def test_side_effecting_tool_refuses_env_default_retry(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "2")
    tool = _FlakyTool(failures=1)
    registry = _registry("write_record", {"params": {}}, tool)

    result = asyncio.run(registry.execute("write_record"))

    assert result.success is False
    assert tool.calls == 1, "side-effecting tool must not retry via env default"


def test_tool_declared_max_retries_wins_over_env_default(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "5")
    tool = _FlakyTool(failures=1)
    registry = _registry(
        "search_declared",
        {"execution": {"max_retries": 1, "retry_delay_ms": 0}},
        tool,
    )

    result = asyncio.run(registry.execute("search_declared"))

    assert result.success is True
    assert tool.calls == 2, "exactly 1 retry, not the env default of 5"


def test_stream_execute_honors_env_default_retry(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "2")
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_BASE", "0")
    tool = _FlakyTool(failures=2)
    registry = _registry("search_stream", {"params": {}}, tool)

    async def collect():
        return [item async for item in registry.stream_execute("search_stream")]

    results = asyncio.run(collect())

    assert results[-1].success is True
    assert tool.calls == 3


def test_env_retry_helpers_parse_and_fall_back(monkeypatch):
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "2")
    assert registry_mod._env_default_max_retries() == 2
    monkeypatch.setenv("NEXUS_TOOL_DEFAULT_MAX_RETRIES", "bogus")
    assert registry_mod._env_default_max_retries() == 0

    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_BASE", "0.25")
    assert registry_mod._env_retry_backoff_base_ms() == 250
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_BASE", "-1")
    assert registry_mod._env_retry_backoff_base_ms() == 500

    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_MAX", "7")
    assert registry_mod._env_retry_backoff_max_ms() == 7000
    monkeypatch.setenv("NEXUS_TOOL_RETRY_BACKOFF_MAX", "bogus")
    assert registry_mod._env_retry_backoff_max_ms() == 15_000