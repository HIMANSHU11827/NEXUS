__version__ = "1.0.0"
from evolution.intent.scripts.engine import NexusIntentEngine


class TestNexusIntent:
    def test_instantiate(self):
        engine = NexusIntentEngine()
        assert engine is not None
