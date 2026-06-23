import pytest
from evolution.nudge.scripts.engine import NudgeEngine


@pytest.fixture
def engine(tmp_path):
    return NudgeEngine(str(tmp_path))


class TestNudgeEngine:
    def test_init(self, engine):
        assert engine.root == str(engine.root)

    def test_state_path(self, engine):
        assert engine.state_path is not None
