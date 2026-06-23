import pytest
from evolution.log import EvolutionLog


@pytest.fixture
def log(tmp_path):
    return EvolutionLog(str(tmp_path))


class TestEvolutionLog:
    def test_init_creates_dir(self, log):
        assert log.root == str(log.root)

    def test_win_log(self, log):
        result = log.win("skill", "test_skill", "Test win", 1.0)
        assert result is not None
        assert result.get("outcome") == "win"

    def test_improvement(self, log):
        result = log.improvement("Added unit tests")
        assert result is not None
        assert result.get("action") == "Added unit tests"

    def test_stats(self, log):
        log.win("skill", "s1", "win")
        log.lose("tool", "t1", "fail")
        stats = log.stats()
        assert isinstance(stats, dict)
        assert "total_events" in stats
