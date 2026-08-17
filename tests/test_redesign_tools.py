"""Tests for the tools/MCP layer redesign:
- strict schema validation (additionalProperties / enum)
- persist-to-disk oversized tool output
- edit precision (replace_all / ambiguous old_string)
- MCP reconnect + parking (degraded/unavailable health, tool deregistration)
"""
import asyncio
import json

import pytest

from tools.nexus_tools.base_tool import BaseTool, ToolResult


# ─────────────────────────────────────────────────────────────────────
# 1. Strict schema validation
# ─────────────────────────────────────────────────────────────────────

class _PassthroughTool(BaseTool):
    """Echoes kwargs through to the output (accepts anything)."""

    async def execute(self, **kwargs):
        return ToolResult(success=True, output=json.dumps(kwargs, default=str))


def _bare_registry(root):
    from tools.nexus_tools.registry import ToolRegistry

    registry = object.__new__(ToolRegistry)
    registry.root = str(root)
    registry._tools = {}
    registry._mcp_clients = []
    return registry


def _registry_with(root, entry):
    registry = _bare_registry(root)
    registry._tools[entry.name] = entry
    return registry


def test_schema_additional_properties_false_rejects_extra_key(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    schema = {"params": {"known": {"type": "string"}}, "additionalProperties": False}
    registry = _registry_with(tmp_path, ToolEntry("strict", schema, _PassthroughTool()))

    with pytest.raises(ValueError, match="undeclared parameter"):
        asyncio.run(registry.execute("strict", known="ok", unknown="nope"))

    # Declared keys still validate and execute.
    result = asyncio.run(registry.execute("strict", known="ok"))
    assert result.success is True


def test_schema_additional_properties_false_in_params_dict(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    # .jsnol form: additionalProperties carried inside the params map.
    schema = {"params": {"known": {"type": "string"}, "additionalProperties": False}}
    registry = _registry_with(tmp_path, ToolEntry("strict2", schema, _PassthroughTool()))

    with pytest.raises(ValueError, match="undeclared parameter"):
        asyncio.run(registry.execute("strict2", known="ok", stray="x"))


def test_schema_unknown_params_allowed_when_not_strict(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    registry = _registry_with(tmp_path, ToolEntry("loose", {"params": {"known": {"type": "string"}}}, _PassthroughTool()))
    result = asyncio.run(registry.execute("loose", known="ok", anything="allowed"))
    assert result.success is True


def test_schema_enum_rejects_out_of_list_value(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    schema = {"params": {"mode": {"type": "string", "enum": ["read", "write"]}}}
    registry = _registry_with(tmp_path, ToolEntry("enummed", schema, _PassthroughTool()))

    with pytest.raises(ValueError, match="must be one of"):
        asyncio.run(registry.execute("enummed", mode="delete"))

    result = asyncio.run(registry.execute("enummed", mode="read"))
    assert result.success is True


# ─────────────────────────────────────────────────────────────────────
# 2. Persist-to-disk oversized output
# ─────────────────────────────────────────────────────────────────────

class _BigOutputTool(BaseTool):
    async def execute(self, **kwargs):
        return ToolResult(success=True, output="x" * 300_000)


def test_oversized_result_persists_with_preview_envelope(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    registry = _registry_with(tmp_path, ToolEntry("big_output", {"params": {}}, _BigOutputTool()))
    result = asyncio.run(registry.execute("big_output"))

    assert result.success is True
    assert result.output.startswith("[Persisted to ")
    assert "len=300000 chars" in result.output
    assert "showing first 4000" in result.output
    # Full output is on disk under context_archive/tool-results/.
    results_dir = tmp_path / "context_archive" / "tool-results"
    files = sorted(results_dir.glob("big_output_*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "x" * 300_000
    assert result.metadata["output_persisted"] == str(files[0])


def test_oversized_stream_result_persists(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    class BigStreamTool(BaseTool):
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="y" * 250_000)

    registry = _registry_with(tmp_path, ToolEntry("big_stream", {"params": {}}, BigStreamTool()))

    async def collect():
        return [chunk async for chunk in registry.stream_execute("big_stream")]

    chunks = asyncio.run(collect())
    assert len(chunks) == 1
    assert chunks[0].output.startswith("[Persisted to ")
    results_dir = tmp_path / "context_archive" / "tool-results"
    assert any(f.name.startswith("big_stream_") for f in results_dir.glob("*.txt"))


def test_small_output_not_persisted(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    class SmallTool(BaseTool):
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="tiny")

    registry = _registry_with(tmp_path, ToolEntry("small", {"params": {}}, SmallTool()))
    result = asyncio.run(registry.execute("small"))
    assert result.output == "tiny"
    assert not (tmp_path / "context_archive").exists()


def test_elision_flag_result_is_persisted_too(tmp_path):
    from tools.nexus_tools.registry import ToolEntry

    class ElidedTool(BaseTool):
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="already elided", metadata={"output_truncated": True})

    registry = _registry_with(tmp_path, ToolEntry("elided", {"params": {}}, ElidedTool()))
    result = asyncio.run(registry.execute("elided"))
    assert result.output.startswith("[Persisted to ")
    assert "output_persisted" in result.metadata


def test_reading_policy_persists_large_source_previews(tmp_path):
    """Large source reads must not consume the V5 run deadline as a stream."""
    from pathlib import Path
    from tools.nexus_tools.registry import ToolEntry
    from tools.reading.scripts.reading import ReadingTool

    metadata = json.loads(Path("tools/reading/reading.jsnol").read_text(encoding="utf-8"))
    assert metadata["execution"]["max_output_chars"] == 32000

    source = tmp_path / "large_source.py"
    source.write_text("# source\n" + ("value = 1\n" * 6000), encoding="utf-8")
    entry = ToolEntry(
        "reading",
        {
            "params": {"path": {"type": "string", "required": True}},
            "execution": {"max_output_chars": 32000},
        },
        ReadingTool(root_dir=str(tmp_path)),
    )
    registry = _registry_with(tmp_path, entry)

    async def collect():
        return [item async for item in registry.stream_execute("reading", path="large_source.py")]

    results = asyncio.run(collect())
    assert len(results) == 1
    result = results[0]

    assert result.success is True
    assert result.output.startswith("[Persisted to ")
    assert "showing first 4000" in result.output
    archived = list((tmp_path / "context_archive" / "tool-results").glob("*.txt"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_reading_supports_targeted_line_ranges(tmp_path):
    from tools.nexus_tools.registry import ToolEntry
    from tools.reading.scripts.reading import ReadingTool

    source = tmp_path / "source.py"
    source.write_text("".join(f"line_{index}\n" for index in range(1, 21)), encoding="utf-8")
    registry = _registry_with(
        tmp_path,
        ToolEntry(
            "reading",
            {
                "params": {
                    "path": {"type": "string", "required": True},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "execution": {"max_output_chars": 32000},
            },
            ReadingTool(root_dir=str(tmp_path)),
        ),
    )

    result = asyncio.run(registry.execute(
        "reading", path="source.py", start_line=7, end_line=9
    ))

    assert result.success is True
    assert result.output == "line_7\nline_8\nline_9\n"


# ─────────────────────────────────────────────────────────────────────
# 3. Edit precision (modifying)
# ─────────────────────────────────────────────────────────────────────

def _modifying_tool(tmp_path):
    from tools.modifying.scripts.modifying import ModifyingTool

    return ModifyingTool(root_dir=str(tmp_path))


def test_modifying_multiple_matches_requires_context_or_replace_all(tmp_path):
    target = tmp_path / "doc.txt"
    original = "hello world hello world"
    target.write_text(original, encoding="utf-8")

    result = asyncio.run(_modifying_tool(tmp_path).execute(
        path=str(target), old_string="hello world", new_string="bye",
    ))
    assert result.success is False
    assert "Found 2 matches of the old_string" in result.error
    assert "provide more surrounding context or set replace_all: true" in result.error
    # File untouched when the edit is ambiguous.
    assert target.read_text(encoding="utf-8") == original


def test_modifying_replace_all_replaces_every_match(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("hello world hello world", encoding="utf-8")

    result = asyncio.run(_modifying_tool(tmp_path).execute(
        path=str(target), old_string="hello", new_string="bye", replace_all=True,
    ))
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "bye world bye world"
    assert result.metadata["replacements"] == 2


def test_modifying_single_match_still_edits(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("only one hello here", encoding="utf-8")

    result = asyncio.run(_modifying_tool(tmp_path).execute(
        path=str(target), old_string="hello", new_string="goodbye",
    ))
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "only one goodbye here"
    assert result.metadata["replacements"] == 1


def test_modifying_matches_curly_quotes_as_straight(tmp_path):
    target = tmp_path / "quotes.txt"
    target.write_text("it’s fine today", encoding="utf-8")

    result = asyncio.run(_modifying_tool(tmp_path).execute(
        path=str(target), old_string="it's", new_string="it is",
    ))
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "it is fine today"


# ─────────────────────────────────────────────────────────────────────
# 4. MCP reconnect + parking
# ─────────────────────────────────────────────────────────────────────

def test_mcp_health_probe_tristate():
    from mcp.client.scripts.client import MCPClient

    client = MCPClient("nope", [])
    # Not started yet → unavailable.
    assert client.health_probe() == "unavailable"

    client.state = "degraded"
    assert client.health_probe() == "degraded"

    client.state = "healthy"
    # Never falsely healthy while the child process is absent.
    assert client.health_probe() == "degraded"


def test_mcp_transport_failure_parks_tools_and_not_healthy(tmp_path):
    from mcp.client.scripts.client import MCPClient
    from tools.nexus_tools.registry import ToolRegistry

    registry = _bare_registry(tmp_path)
    client = MCPClient("nonexistent-binary", [])
    client.start = lambda: False                 # cannot be restarted
    client._probe_tools = lambda: None
    client.degraded_cb = lambda: registry._deregister_mcp_tools("math")
    client.recover_cb = lambda tools: registry._register_mcp_tools("math", client, tools)

    tool_defs = [
        {"name": "math_add", "description": "add", "inputSchema": {"properties": {}}},
        {"name": "math_sub", "description": "subtract", "inputSchema": {"properties": {}}},
    ]
    registry._register_mcp_tools("math", client, tool_defs)
    assert set(registry._tools) == {"math_add", "math_sub"}

    # Transport write failure → lazy reconnect (no timers).  Server cannot come
    # back, so bounded attempts exhaust → unavailable and tools are parked.
    assert client._recover(max_attempts=1) is False
    assert "math_add" not in registry._tools
    assert "math_sub" not in registry._tools
    assert client.health_probe() in ("degraded", "unavailable")


def test_mcp_recovery_restores_tools_and_healthy(tmp_path):
    from mcp.client.scripts.client import MCPClient
    from tools.nexus_tools.registry import ToolRegistry

    class FakeProcess:
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return None
        def kill(self):
            pass

    registry = _bare_registry(tmp_path)
    client = MCPClient("fake-mcp", [])
    tool_defs = [
        {"name": "math_add", "description": "add", "inputSchema": {"properties": {}}},
        {"name": "math_sub", "description": "subtract", "inputSchema": {"properties": {}}},
    ]
    client.process = FakeProcess()               # so is_running() is True
    client.start = lambda: True
    client._probe_tools = lambda: tool_defs       # re-probe succeeds
    client.degraded_cb = lambda: registry._deregister_mcp_tools("math")
    client.recover_cb = lambda tools: registry._register_mcp_tools("math", client, tools)

    registry._register_mcp_tools("math", client, tool_defs)
    assert set(registry._tools) == {"math_add", "math_sub"}

    # One transport failure → recovery re-registers tools and clears degraded.
    assert client._recover(max_attempts=2) is True
    assert client.health_probe() == "healthy"
    assert set(registry._tools) == {"math_add", "math_sub"}


def test_init_mcp_drops_unavailable_server(tmp_path, monkeypatch):
    from tools.nexus_tools.registry import ToolRegistry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "mcp_servers.json").write_text(
        json.dumps({"servers": [{"name": "dead", "command": "no-such-bin", "args": []}]}),
        encoding="utf-8",
    )

    class DeadClient:
        def __init__(self, command, args):
            self.command = command

        def start(self):
            return True

        def health_probe(self):
            return "unavailable"

        def list_tools(self):
            return []

    monkeypatch.setattr("mcp.client.MCPClient", DeadClient)

    registry = _bare_registry(tmp_path)
    assert registry.init_mcp_tools() == 0
    assert registry._tools == {}
