import asyncio

from tools.nexus_tools.registry import ToolEntry, ToolRegistry
from tools.nexus_tools.base_tool import ToolResult


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


def test_side_effecting_tool_does_not_retry_without_explicit_opt_in():
    tool = _FlakyTool()
    registry = _registry(
        "write_record",
        {"execution": {"max_retries": 2, "retry_delay_ms": 0}},
        tool,
    )

    result = asyncio.run(registry.execute("write_record"))

    assert result.status == "error"
    assert tool.calls == 1


def test_read_only_tool_keeps_configured_transient_retry():
    tool = _FlakyTool()
    registry = _registry(
        "search_records",
        {"execution": {"max_retries": 1, "retry_delay_ms": 0}},
        tool,
    )

    result = asyncio.run(registry.execute("search_records"))

    assert result.success is True
    assert tool.calls == 2


def test_side_effecting_tool_can_opt_into_retries_when_adapter_is_idempotent():
    tool = _FlakyTool()
    registry = _registry(
        "send_message",
        {"execution": {"max_retries": 1, "retry_delay_ms": 0, "retry_side_effects": True}},
        tool,
    )

    result = asyncio.run(registry.execute("send_message"))

    assert result.success is True
    assert tool.calls == 2


def test_retry_safety_does_not_trust_get_like_mutating_tool_name():
    tool = _FlakyTool()
    registry = _registry(
        "get_or_create_record",
        {"execution": {"max_retries": 1, "retry_delay_ms": 0}},
        tool,
    )

    result = asyncio.run(registry.execute("get_or_create_record"))

    assert result.status == "error"
    assert tool.calls == 1


def test_streaming_side_effecting_tool_also_suppresses_retry_by_default():
    tool = _FlakyTool()
    registry = _registry(
        "update_record",
        {"execution": {"max_retries": 2, "retry_delay_ms": 0}},
        tool,
    )

    results = list(asyncio.run(_collect(registry.stream_execute("update_record"))))

    assert results[-1].status == "error"
    assert tool.calls == 1


async def _collect(stream):
    return [item async for item in stream]
