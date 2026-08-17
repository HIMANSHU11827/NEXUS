import json

import pytest

from extensions.tools.built_in.ask_question.scripts.ask_question import AskQuestionTool
from extensions.tools.built_in.nexus_tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_ask_question_returns_surface_compatible_marker():
    result = await AskQuestionTool(".").execute(
        prompt="Which direction should we take?",
        options=["Build", "Fix", "Research"],
    )

    assert result.success is True
    assert result.output.startswith("[QUESTION:")
    payload = json.loads(result.output[len("[QUESTION:"):-1])
    assert payload["prompt"] == "Which direction should we take?"
    assert payload["options"] == ["Build", "Fix", "Research"]
    assert payload["allowCustom"] is True
    assert result.metadata["question"] == payload


@pytest.mark.asyncio
async def test_ask_question_normalizes_and_bounds_options():
    result = await AskQuestionTool(".").execute(
        prompt="Pick one",
        options=[" A ", "A", "", *[f"Choice {i}" for i in range(1, 10)]],
        allow_custom=False,
    )

    payload = result.metadata["question"]
    assert payload["options"] == ["A", "Choice 1", "Choice 2", "Choice 3", "Choice 4", "Choice 5", "Choice 6", "Choice 7"]
    assert payload["allowCustom"] is False


@pytest.mark.asyncio
async def test_ask_question_rejects_missing_input():
    tool = AskQuestionTool(".")
    assert (await tool.execute(prompt="", options=["Yes"])).success is False
    assert (await tool.execute(prompt="Continue?", options=[])).success is False


def test_ask_question_is_discovered_by_registry():
    # The registry discovers from the repository root.
    real_registry = ToolRegistry()
    try:
        entry = real_registry.get("ask_question")
        assert entry is not None
        assert entry.is_available()
        assert entry.is_read_only() is False
    finally:
        real_registry.close()
