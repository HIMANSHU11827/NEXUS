__version__ = "1.0.0"
import pytest
from evolution.status.scripts.status import EvolutionStatus


@pytest.fixture
def status(tmp_path):
    return EvolutionStatus(str(tmp_path))


class TestEvolutionStatus:
    def test_init(self, status):
        assert status.root == str(status.root)

    def test_report(self, status):
        report = status.report()
        assert isinstance(report, dict)
        assert "skills" in report
