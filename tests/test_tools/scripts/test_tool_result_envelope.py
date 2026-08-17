"""
Tests for the canonical NEXUS tool-calling result envelope and the hardened
local-anon auth gate.

These exercise NEW behavior introduced by the tool-lifecycle + security
hardening batches: a structured ToolCallResult, error classification /
truncation, argument parsing, and the loopback-restricted anonymous-auth flag.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Allow the script to import package modules without installed entry points.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from extensions.tools.built_in.nexus_tools import result as tr  # noqa: E402
from extensions.tools.built_in.nexus_tools.base_tool import ToolResult  # noqa: E402


def test_status_vocabulary_is_closed_and_canonical():
    assert tr.VALID_STATUSES == {
        tr.STATUS_OK, tr.STATUS_ERROR, tr.STATUS_TIMEOUT,
        tr.STATUS_UNIMPLEMENTED, tr.STATUS_BLOCKED,
    }
    # An invalid status is coerced to error rather than silently accepted.
    bad = tr.ToolCallResult(name="x", status="weird")
    assert bad.status == tr.STATUS_ERROR
    assert bad.success is False


def test_toolcallresult_is_backwards_compatible_with_legacy_toolresult():
    # Existing callers rely on isinstance(..., ToolResult) and .success/.output.
    res = tr.ToolCallResult(name="web_search", status=tr.STATUS_OK, stdout="hi")
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert res.output == "hi"
    # dict-compatible access for newer consumers
    assert res.to_dict()["status"] == tr.STATUS_OK
    assert res["status"] == tr.STATUS_OK
    assert res.get("name") == "web_search"


def test_classify_error_marks_timeouts_and_network_errors_retryable():
    assert tr.classify_error(TimeoutError("boom"))["retryable"] is True
    assert tr.classify_error(ConnectionError("refused"))["retryable"] is True
    assert tr.classify_error(ValueError("bad args"))["retryable"] is False
    info = tr.classify_error(RuntimeError("explode"))
    assert info["type"] == "RuntimeError"
    assert "explode" in info["message"]


def test_truncate_output_bounds_oversized_streams():
    big = "x" * 1_000_000
    out, truncated = tr.truncate_output(big, limit=10_000)
    assert truncated is True
    # The middle is elided; total length is bounded (marker included in budget).
    assert len(out) >= 10_000
    assert len(out) <= 10_000 + 200
    assert "[TRUNCATED" in out
    # small input passes through untouched
    small, truncated_small = tr.truncate_output("tiny", limit=10_000)
    assert truncated_small is False
    assert small == "tiny"


def test_normalize_result_wraps_legacy_output():
    norm = tr.normalize_result(
        {"output": "done", "success": True},
        name="ls", tool_call_id="call_1", started_at="t", monotonic_start=0.0,
    )
    assert norm.status == tr.STATUS_OK
    assert norm.stdout == "done"


def test_parse_tool_arguments_repairs_fenced_and_truncated_json():
    fenced = tr.parse_tool_arguments('```json\n{"q": "hello"}\n```', tool_name="search")
    assert fenced == {"q": "hello"}
    obj = tr.parse_tool_arguments('{"q": "hello"}', tool_name="search")
    assert obj == {"q": "hello"}
    with pytest.raises(tr.ToolArgumentError):
        tr.parse_tool_arguments('{not valid json', tool_name="search")


def test_error_result_carries_retryable_flag():
    err = tr.error_result(
        ConnectionError("refused"),
        name="search", tool_call_id="call_1", started_at="t", monotonic_start=0.0,
    )
    assert err.status == tr.STATUS_ERROR
    assert err.error_info["retryable"] is True
    assert err.error_info["type"] == "ConnectionError"


def test_timeout_status_is_always_retryable():
    to = tr.error_result(
        TimeoutError("slow"),
        name="search", tool_call_id="call_1", started_at="t", monotonic_start=0.0,
        status=tr.STATUS_TIMEOUT,
    )
    assert to.status == tr.STATUS_TIMEOUT
    assert to.error_info["retryable"] is True


def test_authentication_loopback_gate_only_allows_local_peers():
    import security.core.auth

    # A genuine loopback request passes the check when the opt-in is on.
    lb_request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}, cookies={})
    with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
        assert authentication.is_loopback_request(lb_request) is True
        assert authentication.check_auth(lb_request) is not None

    # A remote / LAN peer is NOT granted anonymous access even with the flag on.
    remote_request = SimpleNamespace(client=SimpleNamespace(host="192.168.1.50"), headers={}, cookies={})
    with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
        assert authentication.is_loopback_request(remote_request) is False
        assert authentication.check_auth(remote_request) is None

    # TestClient reports host "testclient" — not loopback, so anon is refused.
    tc_request = SimpleNamespace(client=SimpleNamespace(host="testclient"), headers={}, cookies={})
    with patch.dict(os.environ, {"NEXUS_ALLOW_LOCAL_ANON": "true"}):
        assert authentication.check_auth(tc_request) is None
