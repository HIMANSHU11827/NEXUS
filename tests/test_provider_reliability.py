"""Regression tests for provider-layer reliability fixes.

Covers:
- Anthropic stream wraps extended-thinking deltas in <thinking> markers.
- Anthropic end-of-stream surfaces API-reported token usage on _last_usage.
- Gemini honors a per-call ``model`` override in body and URL.
- ``reload_credentials()`` re-reads a fresher env/config key and rebuilds
  auth headers.  All requests are monkeypatched — no network.
"""

import json

from models.providers.api.anthropic import AnthropicProvider
from models.providers.api.google_gemini import GoogleGeminiProvider
from models.providers.api.xai import XAIProvider


def _sse(events):
    """Render Anthropic-style SSE ``data: {...}`` bytes for a fake response."""
    return [("data: " + json.dumps(event)).encode("utf-8") for event in events]


def test_anthropic_stream_wraps_thinking_in_markers(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            return iter(_sse([
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "thinking", "thinking": ""}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "thinking_delta", "thinking": "Let me reason"}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "thinking_delta", "thinking": " step by step."}},
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1,
                 "content_block": {"type": "text", "text": "Sure,"}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "text_delta", "text": " here you go."}},
                {"type": "content_block_stop", "index": 1},
                {"type": "message_stop"},
            ]))

    monkeypatch.setattr(provider.session, "post", lambda *a, **kw: Response())
    result = list(provider.stream_generate(messages=[{"role": "user", "content": "hi"}]))
    assert result == [
        "<thinking>", "Let me reason", " step by step.", "</thinking>",
        "Sure,", " here you go.",
    ]
    # No usage reported -> nothing surfaced.
    assert provider._last_usage is None


def test_anthropic_stream_redacted_thinking_uses_markers(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            return iter(_sse([
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "redacted_thinking", "data": "..."}},
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1,
                 "content_block": {"type": "text", "text": "Final answer"}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "text_delta", "text": " here."}},
                {"type": "content_block_stop", "index": 1},
                {"type": "message_stop"},
            ]))

    monkeypatch.setattr(provider.session, "post", lambda *a, **kw: Response())
    result = list(provider.stream_generate(messages=[{"role": "user", "content": "hi"}]))
    assert result == ["<thinking>[redacted reasoning]", "</thinking>", "Final answer", " here."]


def test_anthropic_stream_surfaces_last_usage(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            return iter(_sse([
                {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": "Hello"}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": " world"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "usage": {"output_tokens": 8}},
                {"type": "message_stop"},
            ]))

    monkeypatch.setattr(provider.session, "post", lambda *a, **kw: Response())
    chunks = list(provider.stream_generate(messages=[{"role": "user", "content": "hi"}]))
    assert chunks == ["Hello", " world"]
    assert provider._last_usage == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


def test_gemini_generate_honors_model_override(monkeypatch):
    provider = GoogleGeminiProvider()
    provider.api_key = "test-key"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

    def post(*args, **kwargs):
        captured["url"] = args[0] if args else ""
        captured["json"] = kwargs.get("json", {})
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    provider.generate(messages=[{"role": "user", "content": "hi"}], model="gemini-2.5-flash")
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
    )
    assert captured["json"]["model"] == "gemini-2.5-flash"

    # No override -> the configured default model is preserved end-to-end.
    provider.generate(messages=[{"role": "user", "content": "hi"}])
    assert captured["json"]["model"] == provider._default_model
    assert captured["url"].startswith("https://generativelanguage.googleapis.com/")


def test_gemini_stream_honors_model_override(monkeypatch):
    provider = GoogleGeminiProvider()
    provider.api_key = "test-key"
    captured = {}

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            return iter([
                b'[,{"candidates":[{"content":{"parts":[{"text":"hi"}]}}]},',
                b"]",
            ])

    def post(*args, **kwargs):
        captured["url"] = args[0] if args else ""
        captured["json"] = kwargs.get("json", {})
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    list(provider.stream_generate(
        messages=[{"role": "user", "content": "hi"}], model="gemini-2.5-pro"
    ))
    assert captured["url"].endswith("/models/gemini-2.5-pro:streamGenerateContent")
    assert captured["json"]["model"] == "gemini-2.5-pro"


def test_reload_credentials_picks_up_new_env_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "old-key")
    provider = AnthropicProvider()
    assert provider.api_key == "old-key"
    assert provider.headers.get("x-api-key") == "old-key"

    # Credential rotated under the provider; a re-read must update the key and
    # the raw auth header it is baked into.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "new-key")
    assert provider.reload_credentials() is True
    assert provider.api_key == "new-key"
    assert provider.headers.get("x-api-key") == "new-key"


def test_reload_credentials_explicit_key_rebuilds_bearer_header():
    provider = XAIProvider()
    provider.api_key = "stale"
    provider.headers["Authorization"] = "Bearer stale"

    assert provider.reload_credentials("fresh-key") is True
    assert provider.api_key == "fresh-key"
    assert provider.headers["Authorization"] == "Bearer fresh-key"


def test_reload_credentials_noop_when_key_unchanged():
    provider = XAIProvider()
    provider.api_key = "same"
    provider.headers["Authorization"] = "Bearer same"

    assert provider.reload_credentials("same") is False
    assert provider.api_key == "same"
    assert provider.headers["Authorization"] == "Bearer same"
