"""Focused regressions for registry and skill execution boundaries."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from orchestrators.v5.skill import V5Skill
from skills.registry import SkillRegistry
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.registry import ToolEntry, ToolRegistry
from tools.nexus_tools.result import ToolCallResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _registry(entry: ToolEntry) -> ToolRegistry:
    registry = object.__new__(ToolRegistry)
    registry.root = str(PROJECT_ROOT)
    registry._tools = {entry.name: entry}
    registry._mcp_clients = []
    return registry


class _EchoTool(BaseTool):
    async def execute(self, **kwargs):
        return ToolResult(success=True, output=json.dumps(kwargs, sort_keys=True))


def test_required_and_typed_parameters_reject_null_before_handler_runs():
    class TrackingTool(_EchoTool):
        def __init__(self):
            super().__init__(str(PROJECT_ROOT))
            self.called = False

        async def execute(self, **kwargs):
            self.called = True
            return await super().execute(**kwargs)

    handler = TrackingTool()
    entry = ToolEntry(
        "creating",
        {
            "params": {
                "path": {"type": "string", "required": True},
                "content": {"type": "string", "required": True},
                "label": {"type": "string"},
            }
        },
        handler,
    )
    registry = _registry(entry)

    with pytest.raises(ValueError, match="requires non-null parameter 'path'"):
        asyncio.run(registry.execute("creating", path=None, content="x"))
    with pytest.raises(TypeError, match="parameter 'label' must be string"):
        asyncio.run(registry.execute("creating", path="x", content="y", label=None))
    assert handler.called is False


def test_params_level_additional_properties_accepts_valid_call_and_rejects_extra():
    entry = ToolEntry(
        "strict",
        {"params": {"known": {"type": "string"}, "additionalProperties": False}},
        _EchoTool(str(PROJECT_ROOT)),
    )
    registry = _registry(entry)

    result = asyncio.run(registry.execute("strict", known="ok"))
    assert result.status == "ok"
    assert json.loads(result.output) == {"known": "ok"}

    with pytest.raises(ValueError, match="undeclared parameter"):
        asyncio.run(registry.execute("strict", known="ok", stray="no"))


def test_recursive_json_schema_validation_blocks_invalid_nested_values_before_execution():
    class TrackingTool(_EchoTool):
        def __init__(self):
            super().__init__(str(PROJECT_ROOT))
            self.calls = 0

        async def execute(self, **kwargs):
            self.calls += 1
            return await super().execute(**kwargs)

    handler = TrackingTool()
    schema = {
        "params": {
            "config": {
                "type": "object",
                "required": ["name", "retries", "tags"],
                "properties": {
                    "name": {"type": "string", "pattern": r"^[a-z][a-z0-9_-]+$"},
                    "retries": {"type": "integer", "minimum": 1, "maximum": 3},
                    "tags": {
                        "type": "array", "minItems": 1, "maxItems": 2,
                        "items": {"type": "string", "pattern": r"^[a-z]+$"},
                    },
                },
                "additionalProperties": False,
            }
        },
        "required": ["config"],
    }
    registry = _registry(ToolEntry("nested", schema, handler))

    valid = asyncio.run(registry.execute(
        "nested", config={"name": "worker_1", "retries": 2, "tags": ["safe"]},
    ))
    assert valid.status == "ok"
    assert handler.calls == 1

    invalid_calls = [
        ({"name": "Bad", "retries": 2, "tags": ["safe"]}, "does not match pattern"),
        ({"name": "worker", "retries": 4, "tags": ["safe"]}, "must be <= 3"),
        ({"name": "worker", "retries": 2, "tags": []}, "minItems 1"),
        ({"name": "worker", "retries": 2, "tags": ["safe", "BAD"]}, "does not match pattern"),
        ({"name": "worker", "retries": 2, "tags": ["safe"], "secret": "no"}, "undeclared parameter"),
    ]
    for config, message in invalid_calls:
        with pytest.raises((TypeError, ValueError), match=message):
            asyncio.run(registry.execute("nested", config=config))
    assert handler.calls == 1


def test_recursive_schema_validates_additional_property_schema_and_array_item_types():
    entry = ToolEntry(
        "dynamic",
        {
            "params": {
                "labels": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "minimum": 0},
                },
                "values": {"type": "array", "items": {"type": "number"}},
            }
        },
        _EchoTool(str(PROJECT_ROOT)),
    )
    registry = _registry(entry)

    assert asyncio.run(registry.execute(
        "dynamic", labels={"one": 1}, values=[1, 2.5],
    )).status == "ok"
    with pytest.raises(TypeError, match=r"labels\.one.*integer"):
        asyncio.run(registry.execute("dynamic", labels={"one": "1"}, values=[1]))
    with pytest.raises(TypeError, match=r"values\[1\].*number"):
        asyncio.run(registry.execute("dynamic", labels={}, values=[1, "2"]))


def test_execute_normalizes_legacy_and_mapping_results():
    legacy = _registry(ToolEntry("legacy", {"params": {}}, _EchoTool(str(PROJECT_ROOT))))
    result = asyncio.run(legacy.execute("legacy", value="x"))

    assert isinstance(result, ToolCallResult)
    assert isinstance(result, ToolResult)
    assert result.name == "legacy"
    assert result.status == "ok"
    assert result.tool_call_id
    assert result.started_at and result.finished_at

    class MappingFailure(BaseTool):
        async def execute(self, **kwargs):
            return {"success": False, "error": "mapped failure"}

    mapping = _registry(
        ToolEntry("mapping", {"params": {}}, MappingFailure(str(PROJECT_ROOT)))
    )
    failed = asyncio.run(mapping.execute("mapping"))
    assert isinstance(failed, ToolCallResult)
    assert failed.status == "error"
    assert failed.error == "mapped failure"


def test_normalization_preserves_full_output_for_registry_persistence():
    class LargeTool(BaseTool):
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="0123456789")

    registry = _registry(
        ToolEntry(
            "large",
            {"params": {}, "execution": {"max_output_chars": 5}},
            LargeTool(str(PROJECT_ROOT)),
        )
    )
    persisted = {}

    def fake_persist(entry, output_text, call_id=None):
        persisted["text"] = output_text
        persisted["call_id"] = call_id
        return "memory://large-output"

    registry._persist_tool_output = fake_persist
    result = asyncio.run(registry.execute("large"))

    assert persisted["text"] == "0123456789"
    assert result.output.startswith("[Persisted to memory://large-output")
    assert result.metadata["output_persisted"] == "memory://large-output"


def test_stream_retry_emits_only_the_terminal_success_result():
    class FlakyReadTool(BaseTool):
        def __init__(self):
            super().__init__(str(PROJECT_ROOT))
            self.attempts = 0

        def is_read_only(self, params=None):
            return True

        async def execute(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("transient")
            return ToolResult(success=True, output="recovered")

    handler = FlakyReadTool()
    registry = _registry(
        ToolEntry(
            "flaky",
            {"params": {}, "execution": {"max_retries": 1, "retry_delay_ms": 0}},
            handler,
        )
    )

    async def collect():
        return [item async for item in registry.stream_execute("flaky")]

    results = asyncio.run(collect())
    assert handler.attempts == 2
    assert len(results) == 1
    assert isinstance(results[0], ToolCallResult)
    assert results[0].status == "ok"
    assert results[0].output == "recovered"


def test_shipped_skill_yaml_descriptions_use_top_level_values():
    records = {record.id: record for record in SkillRegistry(PROJECT_ROOT).discover()}

    computer = records["computer-use"]
    assert computer.description.startswith("Drive the user's desktop")
    assert computer.description != "|"

    google = records["google-workspace"]
    assert google.description == "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python."
    assert "client credentials" not in google.description


def test_skill_engine_receives_the_workspace_root(monkeypatch):
    captured = {}
    sentinel = object()
    fake_module = types.ModuleType("skills.engine")

    def fake_engine(root):
        captured["root"] = root
        return sentinel

    fake_module.NexusSkillEngine = fake_engine
    monkeypatch.setitem(sys.modules, "skills.engine", fake_module)

    host = V5Skill()
    host.root_dir = str(PROJECT_ROOT / "workspace-under-test")
    assert host._skill_master() is sentinel
    assert captured["root"] == str((PROJECT_ROOT / "workspace-under-test").resolve())


def test_skill_prompt_is_complete_when_bounded_and_compacts_head_and_tail(monkeypatch):
    class Master:
        def __init__(self, prompt):
            self.prompt = prompt

        def find_skill(self, name):
            return {"name": name, "prompt": self.prompt}

    ordinary = "BEGIN\n" + ("instruction\n" * 400) + "END"
    host = V5Skill()
    host.root_dir = str(PROJECT_ROOT)
    host._v5_skill_master = Master(ordinary)
    resolved = host._resolve_slash_skill("/code_review run checks")
    assert resolved["prompt"] == ordinary.strip()
    assert resolved["args"] == "run checks"

    monkeypatch.setenv("NEXUS_SKILL_PROMPT_MAX_CHARS", "3000")
    huge = "HEAD\n" + ("x" * 10_000) + "\nTAIL"
    compacted_host = V5Skill()
    compacted_host.root_dir = str(PROJECT_ROOT)
    compacted_host._v5_skill_master = Master(huge)
    compacted = compacted_host._resolve_slash_skill("/large-skill")["prompt"]
    assert len(compacted) <= 3000
    assert compacted.startswith("HEAD")
    assert compacted.endswith("TAIL")
    assert "SKILL INSTRUCTIONS COMPACTED" in compacted


def test_skill_injection_receives_the_complete_bounded_instruction_block():
    class Master:
        def __init__(self):
            self.used = []

        def find_skill(self, name):
            return {"name": name, "prompt": "BEGIN\n" + ("step\n" * 500) + "END"}

        def record_use(self, name, success=True):
            self.used.append((name, success))

    class Perceived:
        original_input = "/code_review inspect this patch"
        context_summary = "existing context"

    master = Master()
    host = V5Skill()
    host.root_dir = str(PROJECT_ROOT)
    host._v5_skill_master = master
    perceived = Perceived()

    asyncio.run(host._inject_skill_context(perceived))

    assert perceived.original_input == "inspect this patch"
    assert "[SKILL_ACTIVE: code_review]" in perceived.context_summary
    assert "BEGIN" in perceived.context_summary and perceived.context_summary.endswith("END")
    assert master.used == [("code_review", True)]


def test_reading_metadata_declares_read_only_without_losing_existing_limits():
    metadata = json.loads(
        (PROJECT_ROOT / "tools" / "reading" / "reading.jsnol").read_text(encoding="utf-8")
    )
    assert metadata["execution"]["read_only"] is True
    assert metadata["execution"]["max_output_chars"] == 32000
    assert set(metadata["params"]) == {"path", "start_line", "end_line"}


def test_every_base_tool_receives_idempotency_and_cooperative_fencing_context():
    cancel_event = asyncio.Event()
    lease_owned = True
    control = types.SimpleNamespace(
        cancel_event=cancel_event,
        execution_fence=lambda: lease_owned,
    )
    tool = BaseTool(str(PROJECT_ROOT))
    tool.set_runtime_context({"idempotency_key": "queue:task-7", "run_control": control})

    assert tool.idempotency_key == "queue:task-7"
    tool.assert_execution_active()
    lease_owned = False
    with pytest.raises(RuntimeError, match="lease ownership was lost"):
        tool.assert_execution_active()
    lease_owned = True
    cancel_event.set()
    with pytest.raises(RuntimeError, match="fenced"):
        tool.assert_execution_active()


def test_registry_fails_closed_before_calling_handler_when_lease_fence_is_lost():
    class TrackingTool(BaseTool):
        def __init__(self):
            super().__init__(str(PROJECT_ROOT))
            self.called = False

        async def execute(self, **_kwargs):
            self.called = True
            return ToolResult(success=True, output="unsafe")

    handler = TrackingTool()
    entry = ToolEntry("fenced", {"params": {}}, handler)
    registry = _registry(entry)
    control = types.SimpleNamespace(
        cancel_event=asyncio.Event(),
        execution_fence=lambda: False,
    )

    result = asyncio.run(
        registry.execute("fenced", _runtime_context={"run_control": control})
    )

    assert result.success is False
    assert "lease ownership was lost" in result.error
    assert handler.called is False
