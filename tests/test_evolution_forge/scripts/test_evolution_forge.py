import pytest
from evolution.forge.scripts.engine import ToolForge


@pytest.fixture
def forge(tmp_path):
    return ToolForge(str(tmp_path))


class TestToolForge:
    def test_init(self, forge):
        assert forge.root == str(forge.root)

    def test_forge_tool(self, forge, sample_tool_def):
        result = forge.forge(sample_tool_def)
        assert isinstance(result, dict)
