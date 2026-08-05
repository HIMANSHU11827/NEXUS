"""Security tests: web_search direct URL fetch must not enable SSRF.

The ``_fetch_url`` path is reachable from model/user input and, through the
gateway, from remote chat surfaces. It must refuse internal, private,
link-local, and cloud-metadata destinations (fail closed), while still
allowing public URLs. The ``NEXUS_WEB_FETCH_ALLOW_PRIVATE=1`` env opt-out
preserves legitimate local-development fetches.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.web_search.scripts.web_search as ws_mod


def _run(coro):
    return asyncio.run(coro)


class TestSsrFGuard:
    def test_blocks_loopback(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        assert ws_mod._ssrf_block_reason("http://127.0.0.1:8000/") is not None
        assert ws_mod._ssrf_block_reason("http://localhost:8080/") is not None

    def test_blocks_cloud_metadata(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        assert ws_mod._ssrf_block_reason("http://169.254.169.254/latest/meta-data/") is not None
        assert ws_mod._ssrf_block_reason(
            "http://metadata.google.internal/computeMetadata/v1/") is not None

    def test_blocks_private_and_link_local(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        assert ws_mod._ssrf_block_reason("http://192.168.1.10:8080/") is not None
        assert ws_mod._ssrf_block_reason("http://10.0.0.5/") is not None
        assert ws_mod._ssrf_block_reason("http://172.16.0.9/") is not None

    def test_blocks_unsupported_scheme(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        assert ws_mod._ssrf_block_reason("file:///etc/passwd") is not None
        assert ws_mod._ssrf_block_reason("gopher://internal:70/") is not None
        assert ws_mod._ssrf_block_reason("ftp://example.com/x") is not None

    def test_fails_closed_on_unresolvable_hostname(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        monkeypatch.delenv("NEXUS_WEB_FETCH_ALLOW_PRIVATE", raising=False)

        def _no_such_host(host, port, type=None):
            raise OSError("Name or service not known")

        monkeypatch.setattr(ws_mod, "getaddrinfo", _no_such_host)
        assert ws_mod._ssrf_block_reason("http://nonexistent.invalid/") is not None

    def test_allows_public_url(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)

        def _public(host, port, type=None):
            return [(2, 1, 6, "", ("93.184.216.34", port))]

        monkeypatch.setattr(ws_mod, "getaddrinfo", _public)
        assert ws_mod._ssrf_block_reason("https://example.com/public/page") is None

    def test_opt_in_env_allows_private(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", True)
        assert ws_mod._ssrf_block_reason("http://127.0.0.1:9999/") is None
        assert ws_mod._ssrf_block_reason("http://192.168.0.5/") is None


class TestFetchUrlBlockedAtRuntime:
    def test_fetch_url_returns_block_error_without_network(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        tool = ws_mod.WebSearchTool()
        result = _run(tool._fetch_url("http://127.0.0.1:1/", timeout=5, max_chars=5))
        assert result.success is False
        assert "SSRF guard" in result.error
        assert "127.0.0.1" in result.error

    def test_fetch_url_blocks_metadata_url(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_PRIVATE_FETCH_ALLOWED", False)
        tool = ws_mod.WebSearchTool()
        result = _run(tool._fetch_url("http://169.254.169.254/latest/meta-data/", timeout=5, max_chars=5))
        assert result.success is False
        assert "SSRF guard" in result.error
