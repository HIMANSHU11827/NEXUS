import pytest

from extensions.tools.built_in.deep_research.scripts.deep_research import DeepResearchTool


@pytest.mark.asyncio
async def test_decompose_query_awaits_llm_inside_running_loop():
    tool = DeepResearchTool(root_dir=".")

    async def fake_llm(_messages):
        return "- First focused question\n- Second focused question\n"

    tool._llm_call = fake_llm

    result = await tool._decompose_query("research topic", "quick")

    assert result == ["First focused question", "Second focused question"]
