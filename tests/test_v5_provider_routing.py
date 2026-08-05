from nexus.runtime import build_chat_request
from orchestrators.v5.response import V5ResponseBuilder
from providers.profiles import ProviderProfile, ProviderProfileStore


def test_chat_request_preserves_selected_provider_profile_and_model():
    request = build_chat_request({
        "session_id": "gui-session",
        "prompt": "hello",
        "provider": "LM Studio",
        "profile": "local-main",
        "model": "qwen-local",
    })
    assert request.provider == "lm_studio"
    assert request.profile == "local-main"
    assert request.model == "qwen-local"


def test_provider_failure_message_distinguishes_exhausted_credit():
    builder = V5ResponseBuilder()
    builder._provider_hint = "deepseek"
    message = builder._provider_failure_message(
        "[PROVIDER_ERROR]: DeepSeek API returned status 402: insufficient balance"
    )
    assert "balance" in message.lower() or "credit" in message.lower()
    assert "not an api-key configuration error" in message.lower()
    assert "missing" not in message.lower()


def test_profile_fallback_skips_disabled_and_cooling_profiles(tmp_path):
    store = ProviderProfileStore(tmp_path / "profiles.json")
    store.add_profile(ProviderProfile(name="primary", provider="lm_studio", type="api_key", active=False))
    store.add_profile(ProviderProfile(name="cooling", provider="lm_studio", type="api_key", cooldown_until=10**12))
    store.add_profile(ProviderProfile(name="backup", provider="lm_studio", type="api_key", model_id="local-backup"))
    next_profile = store.next_profile("lm_studio", "primary")
    assert next_profile is not None
    assert next_profile.name == "backup"
