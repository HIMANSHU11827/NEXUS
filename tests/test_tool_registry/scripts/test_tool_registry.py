__version__ = "1.0.0"

import os
from unittest.mock import MagicMock, patch

import pytest

from tools.nexus_tools.registry import ToolEntry


class TestToolEntry:
    def test_is_available_no_constraints(self):
        entry = ToolEntry(name="test", schema={}, instance=None)
        assert entry.is_available()

    def test_is_available_check_fn_true(self):
        entry = ToolEntry(name="test", schema={}, instance=None, check_fn=lambda: True)
        assert entry.is_available()

    def test_is_available_check_fn_false(self):
        entry = ToolEntry(name="test", schema={}, instance=None, check_fn=lambda: False)
        assert not entry.is_available()

    def test_is_available_check_fn_exception(self):
        def broken():
            raise RuntimeError("fail")
        entry = ToolEntry(name="test", schema={}, instance=None, check_fn=broken)
        assert not entry.is_available()

    def test_is_available_requires_env_all_set(self):
        with patch.dict(os.environ, {"MY_KEY": "abc", "OTHER_KEY": "xyz"}, clear=True):
            entry = ToolEntry(name="test", schema={}, instance=None, requires_env=["MY_KEY", "OTHER_KEY"])
            assert entry.is_available()

    def test_is_available_requires_env_missing(self):
        with patch.dict(os.environ, {"MY_KEY": "abc"}, clear=True):
            entry = ToolEntry(name="test", schema={}, instance=None, requires_env=["MY_KEY", "MISSING"])
            assert not entry.is_available()
            assert entry.availability() == {
                "available": False,
                "reason": "missing_env",
                "missing_env": ["MISSING"],
            }

    def test_is_available_requires_env_empty(self):
        entry = ToolEntry(name="test", schema={}, instance=None, requires_env=[])
        assert entry.is_available()

    def test_check_fn_takes_priority(self):
        def check():
            return False
        with patch.dict(os.environ, {"SOME_KEY": "exists"}, clear=True):
            entry = ToolEntry(name="test", schema={}, instance=None, check_fn=check, requires_env=["SOME_KEY"])
            assert not entry.is_available()  # check_fn returns False, overrides env check
            assert entry.availability()["reason"] == "check_failed"

    def test_availability_disabled_reason(self):
        entry = ToolEntry(name="test", schema={"execution": {"enabled": False}}, instance=None)
        assert entry.availability() == {
            "available": False,
            "reason": "disabled",
            "missing_env": [],
        }

    def test_is_read_only_by_name(self):
        entry = ToolEntry(name="view_data", schema={}, instance=None)
        assert entry.is_read_only()

    def test_is_read_only_writable_by_name(self):
        entry = ToolEntry(name="update_record", schema={}, instance=None)
        assert not entry.is_read_only()

    def test_is_read_only_delegates_to_instance(self):
        mock = MagicMock()
        mock.is_read_only.return_value = False
        entry = ToolEntry(name="read_file", schema={}, instance=mock)
        assert not entry.is_read_only()

    def test_is_concurrency_safe_read_only(self):
        entry = ToolEntry(name="search_items", schema={}, instance=None)
        assert entry.is_concurrency_safe()

    def test_is_concurrency_safe_not_read_only(self):
        entry = ToolEntry(name="write_data", schema={}, instance=None)
        assert not entry.is_concurrency_safe()

    def test_is_concurrency_safe_delegates(self):
        mock = MagicMock()
        mock.is_concurrency_safe.return_value = True
        entry = ToolEntry(name="write_data", schema={}, instance=mock)
        assert entry.is_concurrency_safe()


def test_registry_uses_explicit_root_when_cwd_differs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    tool_dir = project / "tools" / "demo" / "scripts"
    tool_dir.mkdir(parents=True)
    (project / "tools" / "demo" / "demo.jsnol").write_text(
        '{"name":"demo","version":"1.0.0","description":"Demo","params":{}}',
        encoding="utf-8",
    )

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    from tools.nexus_tools.registry import ToolRegistry
    registry = ToolRegistry(str(project))

    assert "demo" in registry.list_tools(include_unavailable=True)
    assert registry.root == str(project)


def test_registry_summary_explains_unavailable_tools(tmp_path):
    project = tmp_path / "project"
    tool_dir = project / "tools" / "demo" / "scripts"
    tool_dir.mkdir(parents=True)
    (project / "tools" / "demo" / "demo.jsnol").write_text(
        '{"name":"demo","version":"1.0.0","description":"Demo","requires_env":["DEMO_KEY"],"params":{}}',
        encoding="utf-8",
    )

    from tools.nexus_tools.registry import ToolRegistry
    registry = ToolRegistry(str(project))

    assert registry.list_tools() == {}
    summary = registry.list_tools(include_unavailable=True)["demo"]
    assert summary["available"] is False
    assert summary["availability_reason"] == "missing_env"
    assert summary["missing_env"] == ["DEMO_KEY"]
    assert summary["has_handler"] is False


def test_registry_discovers_active_skills_as_model_tools(tmp_path):
    skill_dir = tmp_path / ".opencode" / "skills" / "website_builder"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nid: website_builder\nname: website_builder\ndescription: Build sites\n---\nBuild a local website.",
        encoding="utf-8",
    )

    from tools.nexus_tools.registry import ToolRegistry

    registry = ToolRegistry(str(tmp_path))
    tools = registry.list_tools(include_unavailable=True)

    assert "website_builder" in tools
    assert tools["website_builder"]["description"] == "Build sites"
    assert tools["website_builder"]["has_handler"] is True


def test_registry_discovers_nested_skill_tree(tmp_path):
    skill_dir = tmp_path / "skills" / "software-development" / "python" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nid: nested_code_review\nname: Nested Code Review\ndescription: Review code\n---\nReview the requested code.",
        encoding="utf-8",
    )

    from skills.registry import SkillRegistry

    records = SkillRegistry(str(tmp_path)).discover()
    assert any(record.id == "nested_code_review" for record in records)


def test_registry_accepts_mcp_servers_list_and_normalizes_schema(tmp_path, monkeypatch):
    import json

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "mcp_servers.json").write_text(
        json.dumps({"servers": [{"name": "demo", "command": "demo-mcp", "args": []}]}),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self, command, args):
            self.command = command

        def start(self):
            return True

        def list_tools(self):
            return [{
                "name": "lookup",
                "description": "Look something up",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }]

    monkeypatch.setattr("mcp.client.MCPClient", FakeClient)
    from tools.nexus_tools.registry import ToolRegistry

    registry = ToolRegistry(str(tmp_path))
    entry = registry.get("lookup")

    assert entry is not None
    assert entry.schema["category"] == "mcp"
    assert entry.schema["params"]["query"]["type"] == "string"
    assert entry.schema["required"] == ["query"]


def test_registry_enforces_mcp_top_level_required_fields():
    import asyncio

    from tools.nexus_tools.base_tool import BaseTool, ToolResult
    from tools.nexus_tools.registry import ToolEntry, ToolRegistry

    class RequiredTool(BaseTool):
        async def execute(self, query: str) -> ToolResult:
            return ToolResult(success=True, output=query)

    registry = object.__new__(ToolRegistry)
    registry.root = ""
    registry._tools = {
        "required_tool": ToolEntry(
            "required_tool",
            {"params": {"query": {"type": "string"}}, "required": ["query"]},
            RequiredTool(),
        )
    }

    with pytest.raises(ValueError, match="requires parameter 'query'"):
        asyncio.run(registry.execute("required_tool"))


def test_registry_passes_hidden_runtime_context_without_validating_as_tool_param():
    from tools.nexus_tools.base_tool import BaseTool, ToolResult
    from tools.nexus_tools.registry import ToolEntry, ToolRegistry

    class ContextTool(BaseTool):
        def __init__(self):
            super().__init__()
            self.context = None

        def set_runtime_context(self, context):
            self.context = context

        async def execute(self, value: str) -> ToolResult:
            return ToolResult(success=True, output=f"{value}:{self.context['turn_id']}")

    registry = object.__new__(ToolRegistry)
    registry.root = ""
    registry._tools = {
        "context_tool": ToolEntry(
            "context_tool",
            {"params": {"value": {"type": "string", "required": True}}},
            ContextTool(),
        )
    }

    result = __import__("asyncio").run(
        registry.execute(
            "context_tool",
            value="ok",
            _runtime_context={"turn_id": "turn-123"},
        )
    )

    assert result.success is True
    assert result.output == "ok:turn-123"


def test_registry_binds_stream_runtime_context_after_acquiring_semaphore():
    import asyncio

    from tools.nexus_tools.base_tool import BaseTool, ToolResult
    from tools.nexus_tools.registry import ToolEntry, ToolRegistry

    class BlockingContextTool(BaseTool):
        def __init__(self):
            super().__init__()
            self.context = None
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        def set_runtime_context(self, context):
            self.context = context

        async def stream_execute(self, value: str):
            if value == "first":
                self.started.set()
                await self.release.wait()
            yield ToolResult(success=True, output=f"{value}:{self.context['turn_id']}")

    async def run_concurrently():
        tool = BlockingContextTool()
        registry = object.__new__(ToolRegistry)
        registry.root = ""
        registry._tools = {
            "context_tool": ToolEntry(
                "context_tool",
                {"params": {"value": {"type": "string", "required": True}}},
                tool,
            )
        }

        async def collect(value, turn_id):
            return [
                chunk
                async for chunk in registry.stream_execute(
                    "context_tool",
                    value=value,
                    _runtime_context={"turn_id": turn_id},
                )
            ]

        first = asyncio.create_task(collect("first", "turn-1"))
        await tool.started.wait()
        second = asyncio.create_task(collect("second", "turn-2"))
        await asyncio.sleep(0)

        assert tool.context == {"turn_id": "turn-1"}
        tool.release.set()
        first_result, second_result = await asyncio.gather(first, second)
        return first_result, second_result

    first_result, second_result = asyncio.run(run_concurrently())

    assert first_result[0].output == "first:turn-1"
    assert second_result[0].output == "second:turn-2"


def test_registry_discovers_json_metadata_and_marks_stub_unavailable(tmp_path):
    import asyncio
    import json

    tool_dir = tmp_path / "tools" / "legacy_probe"
    scripts = tool_dir / "scripts"
    scripts.mkdir(parents=True)
    (tool_dir / "legacy_probe.json").write_text(
        json.dumps({"name": "legacy_probe", "description": "legacy"}),
        encoding="utf-8",
    )
    (scripts / "legacy_probe.py").write_text(
        "import json\n"
        "def execute(params):\n"
        "    return json.dumps({'result': 'not yet implemented'})\n",
        encoding="utf-8",
    )

    from tools.nexus_tools.registry import ToolRegistry

    registry = ToolRegistry(str(tmp_path))
    summary = registry.list_tools(include_unavailable=True)["legacy_probe"]
    assert summary["availability_reason"] == "unimplemented"
    assert "legacy_probe" not in registry.list_tools()
    import pytest
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(registry.execute("legacy_probe"))


def test_registry_stream_timeout_applies_to_native_async_generators():
    import asyncio

    from tools.nexus_tools.base_tool import BaseTool
    from tools.nexus_tools.registry import ToolEntry, ToolRegistry

    class HangingTool(BaseTool):
        async def stream_execute(self):
            await asyncio.sleep(10)
            yield "never"

    async def run():
        registry = object.__new__(ToolRegistry)
        registry.root = ""
        registry._tools = {
            "hanging": ToolEntry(
                "hanging",
                {"params": {}, "execution": {"timeout_ms": 10}},
                HangingTool(),
            )
        }
        return [chunk async for chunk in registry.stream_execute("hanging")]

    result = asyncio.run(run())
    assert result and result[0].status == "timeout"
