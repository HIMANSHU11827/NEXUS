import pytest
from evolution.self_improvement.engine import SelfImprovementEngine, ImprovementRecord


@pytest.fixture
def engine(tmp_path):
    return SelfImprovementEngine(str(tmp_path))


class TestSelfImprovement:
    def test_init(self, engine):
        assert engine.root == str(engine.root)

    def test_log_path_exists(self, engine):
        assert engine.log_path is not None
