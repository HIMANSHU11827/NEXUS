"""Tests for apps/tui/setup_wizard — provider-aware connection verification.

These prove the wizard's ``test_provider`` routes each provider family to its
real wire format (OpenAI-compatible, Anthropic, Gemini, local) instead of the
old one-size-fits-all POST that produced false negatives for non-OpenAI
providers.
"""

import importlib.util
import os

from unittest import mock as _m

# The wizard is a sibling app module; load it directly (no package install
# needed) so the test runs under the repo root on PYTHONPATH.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WIZARD_PATH = os.path.join(_ROOT, "apps", "tui", "setup_wizard.py")


def _load_wizard():
    spec = importlib.util.spec_from_file_location("setup_wizard_test", _WIZARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wizard = _load_wizard()


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


def _fake_client(handler):
    """Context-manager fake for httpx.Client that delegates to handler."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            return handler("post", url, json, headers)

        def get(self, url, timeout=None):
            return handler("get", url, None, None)

    return _Client


def test_openai_compatible_happy_path():
    def handler(method, url, json, headers):
        assert headers.get("Authorization") == "Bearer sk-test"
        return _FakeResponse(200, {"choices": [{"message": {"content": "OK"}}]})

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider(
            "deepseek", "sk-test", "https://api.deepseek.com/chat/completions", "deepseek-chat"
        )
    assert ok is True
    assert "OK" in msg


def test_anthropic_uses_x_api_key_header():
    captured = {}

    def handler(method, url, json, headers):
        captured["headers"] = headers
        captured["url"] = url
        return _FakeResponse(200, {"content": [{"text": "OK"}]})

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider(
            "anthropic", "sk-ant", "https://api.anthropic.com/v1/messages", "claude-3-5-haiku-20241022"
        )
    assert ok is True
    assert captured["headers"].get("x-api-key") == "sk-ant"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    assert "api.anthropic.com/v1/messages" in captured["url"]


def test_gemini_uses_generate_content_url_with_key():
    captured = {}

    def handler(method, url, json, headers):
        captured["url"] = url
        return _FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider("gemini", "gem-key", "", "gemini-1.5-flash")
    assert ok is True
    assert "generateContent" in captured["url"]
    assert "key=gem-key" in captured["url"]


def test_local_provider_reachable_without_key():
    def handler(method, url, json, headers):
        if method == "get":
            return _FakeResponse(200)
        return _FakeResponse(404)

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider(
            "ollama", "", "http://127.0.0.1:11434/api/chat", "llama3"
        )
    assert ok is True
    assert "reachable" in msg


def test_local_provider_unreachable_reports_failure():
    def handler(method, url, json, headers):
        raise OSError("connection refused")

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider(
            "ollama", "", "http://127.0.0.1:11434/api/chat", "llama3"
        )
    assert ok is False
    assert "not reachable" in msg


def test_anthropic_without_key_fails_cleanly():
    def handler(method, url, json, headers):
        return _FakeResponse(200)

    with _m.patch("httpx.Client", _fake_client(handler)):
        ok, msg, _ = wizard.test_provider(
            "anthropic", "", "", "claude-3-5-haiku-20241022"
        )
    assert ok is False
    assert "no API key" in msg
