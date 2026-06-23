import pytest
from evolution.knowledge_forge.forge import KnowledgeForge


@pytest.fixture
def forge(tmp_path):
    return KnowledgeForge(str(tmp_path))


class TestKnowledgeForge:
    def test_init(self, forge):
        assert forge.root == str(forge.root)

    def test_lib_dir(self, forge):
        assert forge.lib_dir is not None
