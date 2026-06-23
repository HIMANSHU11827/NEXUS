import pytest
from evolution.memory_forge.scripts.forge import MemoryForge


@pytest.fixture
def forge(tmp_path):
    return MemoryForge(str(tmp_path))


class TestMemoryForge:
    def test_init(self, forge):
        assert forge.root == str(forge.root)

    def test_memory_dir(self, forge):
        assert forge.memory_dir is not None
