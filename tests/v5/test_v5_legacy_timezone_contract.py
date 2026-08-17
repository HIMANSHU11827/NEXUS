import asyncio
from datetime import datetime, timezone


def test_paorr_module_uses_timezone_aware_utc():
    from nexus.main_agent import paorr

    assert paorr.datetime.now(timezone.utc).tzinfo is timezone.utc


def test_consciousness_introspection_timestamp_is_timezone_aware_utc(tmp_path):
    from nexus.main_agent import conscious

    layer = conscious.ConsciousnessLayer(str(tmp_path))
    asyncio.run(layer.process({"confidence": 0.9, "complexity": 0.2}, consciousness_level=7))
    timestamp = layer.introspection_history[-1]["timestamp"]
    assert datetime.fromisoformat(timestamp).tzinfo is not None
    assert datetime.fromisoformat(timestamp).utcoffset() == timezone.utc.utcoffset(None)
