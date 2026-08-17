"""Capabilities hardening: web_search internal retry/backoff behavior.

Verifies that transient network failures (timeouts, refused connections,
HTTP 429/5xx) are retried with the bounded policy while permanent errors
(HTTP 4xx other than 429) and SSRF-blocked fetches are never retried.
"""

import asyncio
import json
from pathlib import Path
from urllib import error as urlerror

import pytest

import tools.web_search.scripts.web_search as ws_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>sample</title>
<item><title>First Result</title><link>https://example.com/1</link><description>desc one</description></item>
<item><title>Second Result</title><link>https://example.com/2</link><description>desc two</description></item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._payload


def _patch_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ws_mod.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def test_transient_network_failures_retry_then_succeed(monkeypatch):
    calls = {"n": 0}
    sleeps = _patch_sleep(monkeypatch)

    def flaky_open(request, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urlerror.URLError(ConnectionRefusedError("refused"))
        return _FakeResponse(_RSS)

    monkeypatch.setattr(ws_mod, "_open_url", flaky_open)
    result = asyncio.run(ws_mod.WebSearchTool().execute(query="climate news"))

    assert result.success is True
    assert "First Result" in result.output
    assert calls["n"] == 3, "3 attempts expected (1 initial + 2 retries)"
    assert len(sleeps) == 2, "backoff sleeps expected after each failed attempt"
    assert all(delay >= 0 for delay in sleeps)


def test_attempts_exhausted_fails_after_max_attempts(monkeypatch):
    calls = {"n": 0}
    sleeps = _patch_sleep(monkeypatch)

    def always_fail(request, timeout):
        calls["n"] += 1
        raise urlerror.URLError(ConnectionResetError("reset"))

    monkeypatch.setattr(ws_mod, "_open_url", always_fail)
    result = asyncio.run(ws_mod.WebSearchTool().execute(query="climate news"))

    assert result.success is False
    # Bing exhausted its 3 attempts, then DDG exhausted its 3 attempts.
    assert calls["n"] == 6
    assert len(sleeps) == 4


def test_permanent_http_400_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def forbidden(request, timeout):
        calls["n"] += 1
        raise urlerror.HTTPError(request.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(ws_mod, "_open_url", forbidden)
    result = asyncio.run(ws_mod.WebSearchTool().execute(query="climate news"))

    assert result.success is False
    assert "400" in result.error
    # Each provider attempted exactly once: no retry amplification of 4xx.
    assert calls["n"] == 2


def test_retry_transient_helper_single_attempt_on_permanent_error(monkeypatch):
    calls = {"n": 0}
    _patch_sleep(monkeypatch)

    def forbidden():
        calls["n"] += 1
        raise urlerror.HTTPError("http://example.com", 404, "Not Found", {}, None)

    with pytest.raises(urlerror.HTTPError):
        ws_mod._retry_transient(forbidden)
    assert calls["n"] == 1


def test_fetch_url_retries_transient_failure_then_succeeds(monkeypatch):
    calls = {"n": 0}
    sleeps = _patch_sleep(monkeypatch)

    def flaky_fetch(request, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urlerror.URLError(TimeoutError("timed out"))
        return (200, b"<html><body>hello world</body></html>")

    monkeypatch.setattr(ws_mod, "_ssrf_block_reason", lambda url: None)
    monkeypatch.setattr(ws_mod, "_fetch_response", flaky_fetch)

    result = asyncio.run(ws_mod.WebSearchTool().execute(query="https://example.com/page"))

    assert result.success is True
    assert "hello world" in result.output
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_fetch_url_persistent_5xx_fails_after_retries(monkeypatch):
    calls = {"n": 0}
    sleeps = _patch_sleep(monkeypatch)

    def server_error(request, timeout):
        calls["n"] += 1
        raise urlerror.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(ws_mod, "_ssrf_block_reason", lambda url: None)
    monkeypatch.setattr(ws_mod, "_fetch_response", server_error)

    result = asyncio.run(ws_mod.WebSearchTool().execute(query="https://example.com/page"))

    assert result.success is False
    assert "503" in result.error
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_ssrf_blocked_fetch_never_touches_network(monkeypatch):
    def explode(request, timeout):
        raise AssertionError("network must not be touched for a blocked URL")

    monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
    monkeypatch.setattr(ws_mod, "_ssrf_block_reason", lambda url: "internal/private address blocked")
    monkeypatch.setattr(ws_mod, "_open_url", explode)
    monkeypatch.setattr(ws_mod, "_fetch_response", explode)

    result = asyncio.run(ws_mod.WebSearchTool().execute(query="http://127.0.0.1:8000/secret"))

    assert result.success is False
    assert "SSRF guard" in result.error


def test_retry_policy_env_parsing(monkeypatch):
    monkeypatch.setenv("NEXUS_WEB_SEARCH_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("NEXUS_WEB_SEARCH_BACKOFF_BASE", "1.25")
    assert ws_mod._web_retry_policy() == (5, 1.25)

    monkeypatch.setenv("NEXUS_WEB_SEARCH_MAX_ATTEMPTS", "bogus")
    monkeypatch.setenv("NEXUS_WEB_SEARCH_BACKOFF_BASE", "-2")
    assert ws_mod._web_retry_policy() == (3, 0.0)

    monkeypatch.delenv("NEXUS_WEB_SEARCH_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("NEXUS_WEB_SEARCH_BACKOFF_BASE", raising=False)
    assert ws_mod._web_retry_policy() == (3, 0.5)


def test_web_search_jsnol_declares_bounded_registry_retry():
    metadata = json.loads(
        (PROJECT_ROOT / "extensions" / "tools" / "built_in" / "web_search" / "web_search.jsnol").read_text(encoding="utf-8")
    )
    assert metadata["execution"]["max_retries"] == 2
    assert metadata["execution"].get("retry_side_effects") is not True