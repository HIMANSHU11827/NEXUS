"""Regression coverage for model tool-argument transport and validation."""

def test_provider_transport_preserves_malformed_arguments():
    from models.providers.api.deepseek import DeepSeekProvider

    envelope = DeepSeekProvider._tool_envelope([
        {"function": {"name": "creating", "arguments": '{"path":'}},
    ])

    assert "__nexus_argument_error" in envelope
    assert "<function=creating>{}" not in envelope


def test_direct_loop_preserves_native_argument_parse_error():
    from nexus.main_agent.core import NexusLoopV5

    calls = NexusLoopV5._part_tool_calls({
        "tool_calls": [{
            "id": "call-1",
            "function": {"name": "creating", "arguments": '{"path":'},
        }],
    })

    assert len(calls) == 1
    assert calls[0].name == "creating"
    assert calls[0].params == {}
    assert calls[0].argument_error


def test_direct_loop_preserves_text_argument_parse_error():
    from nexus.main_agent.core import NexusLoopV5

    loop = NexusLoopV5(".", session_id="text-argument-error")
    _text, calls = loop._model_turn_parts(
        '<function=creating>{"path":'
    )

    assert len(calls) == 1
    assert calls[0].name == "creating"
    assert calls[0].params == {}
    assert "malformed JSON" in calls[0].argument_error


def test_direct_tool_schemas_keep_required_arguments_for_file_creation():
    from nexus.main_agent.core import NexusLoopV5

    loop = NexusLoopV5(".", session_id="tool-argument-schema-test")
    creating = next(
        item for item in loop._get_direct_tool_schemas()
        if item["function"]["name"] == "creating"
    )
    parameters = creating["function"]["parameters"]

    assert parameters["required"] == ["path", "content"]
    assert set(parameters["properties"]) == {"path", "content"}


def test_registry_rejects_missing_required_arguments_before_side_effect():
    import asyncio
    import pytest

    from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult
    from extensions.tools.built_in.nexus_tools.registry import ToolEntry, ToolRegistry

    class RequiredTool(BaseTool):
        def __init__(self):
            super().__init__(root_dir=".")
            self.called = False

        async def execute(self, path: str, content: str):
            self.called = True
            return ToolResult(success=True, output=path)

    handler = RequiredTool()
    registry = object.__new__(ToolRegistry)
    registry.root = "."
    registry._tools = {
        "creating": ToolEntry(
            "creating",
            {"params": {
                "path": {"type": "string", "required": True},
                "content": {"type": "string", "required": True},
            }},
            handler,
        ),
    }
    with pytest.raises(ValueError, match="requires parameter 'path'"):
        asyncio.run(registry.execute("creating", content="not enough"))
    assert handler.called is False
