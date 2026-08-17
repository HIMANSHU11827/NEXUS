from nexus.main_agent.core import NexusLoopV5


def _loop(tmp_path, provider_name="deepseek"):
    loop = object.__new__(NexusLoopV5)
    loop.kernel = None
    loop._brain = type("Brain", (), {
        "provider": type("Provider", (), {"provider_name": provider_name})()
    })()
    return loop


def test_missing_key_message_names_safe_configuration_hint(tmp_path):
    message = _loop(tmp_path)._provider_failure_message("missing or invalid api key")
    assert "DEEPSEEK_API_KEY" in message
    assert "missing" in message
    assert "sk-" not in message


def test_rejected_key_message_does_not_echo_secret(tmp_path):
    message = _loop(tmp_path, "openrouter")._provider_failure_message(
        "401 invalid api key sk-live-super-secret-value"
    )
    assert "OPENROUTER_API_KEY" in message
    assert "rejected its API key" in message
    assert "super-secret" not in message


def test_unsupported_provider_message_is_distinct(tmp_path):
    message = _loop(tmp_path, "made_up")._provider_failure_message("unsupported provider")
    assert "not configured or supported" in message
    assert "MADE_UP_API_KEY" not in message


def test_fallback_uses_routed_provider_before_generic_label(tmp_path):
    loop = _loop(tmp_path, "")
    loop._brain.provider_override = "deepseek"
    loop._last_model_error = "missing or invalid api key"
    perceived = type("Perceived", (), {"original_input": "hello"})()
    message = loop._compose_fallback_response(perceived, {"success": None})
    assert "selected provider 'deepseek'" in message
    assert "configured provider'" not in message
