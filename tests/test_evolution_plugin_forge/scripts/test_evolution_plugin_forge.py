import pytest
from evolution.plugin_forge.scripts.forge import PluginForge


@pytest.fixture
def forge(tmp_path):
    return PluginForge(str(tmp_path))


class TestPluginForge:
    def test_init(self, forge):
        assert forge.root == str(forge.root)

    def test_forge_plugin(self, forge, sample_plugin_name):
        result = forge.forge(sample_plugin_name, "A test plugin")
        assert isinstance(result, dict)
