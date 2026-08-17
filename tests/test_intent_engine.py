from nexus.conversation.intent_engine import IntentEngine, NexusIntent


def test_intent_engine_returns_compatible_mapping_for_high_signal_requests():
    result = IntentEngine().classify("Implement the repository upgrade and run tests")

    assert result["intent"] == NexusIntent.MISSION.value
    assert result["needs_tools"] is True
    assert 0.0 <= result["confidence"] <= 1.0


def test_intent_engine_classifies_diagnostics_without_provider_calls():
    result = IntentEngine().classify("Why is the service failing with an exception?")

    assert result["intent"] == NexusIntent.DIAGNOSTIC.value
    assert result["needs_tools"] is True


def test_model_router_required_tier_accepts_legacy_mapping_result():
    from models.providers.core.router import ModelRouter

    router = object.__new__(ModelRouter)
    router.intent_engine = IntentEngine()

    assert router._get_required_tier([{"role": "user", "content": "audit the architecture"}]) == "EXTREME"
    assert router._get_required_tier([{"role": "user", "content": "hello there"}]) == "NANO"
