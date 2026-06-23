import pytest
from evolution.skill_forge.scripts.forge import SkillForge


@pytest.fixture
def forge(tmp_path):
    return SkillForge(str(tmp_path))


class TestSkillForge:
    def test_init(self, forge):
        assert forge.root == str(forge.root)

    def test_forge_skill(self, forge, sample_skill_name):
        result = forge.forge(sample_skill_name, "A test skill")
        assert isinstance(result, dict)
