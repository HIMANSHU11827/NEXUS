from models.providers.core.attempts import ProviderAttemptRecorder
from models.providers.core.reliability import classify_failure


def test_provider_attempt_recorder_is_bounded_and_redacts_secrets():
    recorder = ProviderAttemptRecorder(max_entries=2)
    recorder.record("openai", status="failed", classification=classify_failure(body="401"),
                    reason="https://x.test/?api_key=sk-secret-value")
    recorder.record("gemini", status="success")
    recorder.record("groq", status="fallback", reason="bearer secret-token-value")

    entries = recorder.snapshot()
    assert [entry["provider_id"] for entry in entries] == ["gemini", "groq"]
    assert "sk-secret-value" not in str(entries)
    assert "secret-token-value" not in str(entries)


def test_provider_attempt_recorder_captures_safe_failure_class():
    recorder = ProviderAttemptRecorder()
    entry = recorder.record("openrouter", status="failed",
                            classification=classify_failure(body="429 rate limit"),
                            reason="rate limit")
    assert entry.failure_class
    assert entry.status == "failed"
