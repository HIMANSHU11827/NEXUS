import pytest
from evolution.ledger.scripts.ledger import EvolutionLedger


@pytest.fixture
def ledger(tmp_path):
    return EvolutionLedger(str(tmp_path))


class TestEvolutionLedger:
    def test_init(self, ledger):
        assert ledger.root == str(ledger.root)

    def test_record_event(self, ledger):
        entry = ledger.record("test", "Test event")
        assert entry is not None
        assert entry.get("kind") == "test"

    def test_summary(self, ledger):
        ledger.record("test", "event1")
        s = ledger.summary()
        assert s["total_events"] >= 1
