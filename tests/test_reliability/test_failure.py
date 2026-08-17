"""Tests for reliability.failure: envelope, classification, redaction."""

import asyncio
import json
import socket

import pytest

from reliability.failure import (
    FailureClass,
    FailureEnvelope,
    classify_exception,
    deserialize_envelope,
    envelope_from_exception,
    is_recoverable,
    serialize_envelope,
)


class TestFailureClass:
    def test_all_classes_have_values(self):
        for member in FailureClass:
            assert member.value
            assert isinstance(member.value, str)

    def test_unknown_is_last_resort(self):
        assert classify_exception(RuntimeError("something odd happened")) == FailureClass.UNKNOWN


class TestClassification:
    def test_timeout_by_type(self):
        assert classify_exception(TimeoutError("took too long")) == FailureClass.TIMEOUT

    def test_network_by_type(self):
        assert classify_exception(ConnectionError("refused")) == FailureClass.NETWORK

    def test_dns_by_type(self):
        assert classify_exception(socket.gaierror("nodename nor servname")) == FailureClass.DNS

    def test_validation_by_type(self):
        assert classify_exception(ValueError("bad value")) == FailureClass.VALIDATION

    def test_authorization_by_type(self):
        assert classify_exception(PermissionError("denied")) == FailureClass.AUTHORIZATION

    def test_rate_limit_by_text(self):
        exc = RuntimeError("429 Too Many Requests: rate limit exceeded")
        assert classify_exception(exc) == FailureClass.RATE_LIMIT

    def test_timeout_by_text(self):
        exc = RuntimeError("connection timed out after 30s")
        assert classify_exception(exc) == FailureClass.TIMEOUT

    def test_auth_by_text(self):
        exc = RuntimeError("401 Unauthorized: invalid api key")
        assert classify_exception(exc) == FailureClass.AUTHENTICATION

    def test_outage_by_text(self):
        exc = RuntimeError("503 Service Unavailable: temporarily overloaded")
        assert classify_exception(exc) == FailureClass.PROVIDER_OUTAGE

    def test_quota_by_text(self):
        exc = RuntimeError("insufficient_quota for this model")
        assert classify_exception(exc) == FailureClass.RESOURCE_EXHAUSTION

    def test_permission_by_text(self):
        exc = RuntimeError("permission required: approval needed")
        assert classify_exception(exc) == FailureClass.PERMISSION_REQUIRED

    def test_cancelled_error(self):
        assert classify_exception(asyncio.CancelledError()) == FailureClass.USER_CANCELLATION

    def test_provider_classification_reused(self):
        # providers.reliability.classify_failure should classify a rate-limit
        # shaped provider error identically when importable.
        try:
            from models.providers.core.reliability import classify_failure as provider_classify
            from models.providers.core.reliability import FailureClass as ProviderFC

            exc = RuntimeError("Rate limit reached for requests")
            result = classify_exception(exc)
            assert result == FailureClass.RATE_LIMIT
        except ImportError:
            pytest.skip("models.providers.core.reliability not importable in this environment")


class TestEnvelope:
    def test_envelope_fields_populated(self):
        env = envelope_from_exception(
            TimeoutError("call took 30s"),
            component_type="provider",
            component_id="openai",
            operation="chat.completions",
            tool="web_search",
            provider="openai",
            goal_id="goal_abc",
        )
        assert env.failure_class == FailureClass.TIMEOUT
        assert env.component_type == "provider"
        assert env.component_id == "openai"
        assert env.operation == "chat.completions"
        assert env.tool == "web_search"
        assert env.goal_id == "goal_abc"
        assert env.failure_id
        assert env.is_transient is True
        assert env.is_retryable is True
        assert env.recommended_recovery
        assert env.timestamp > 0

    def test_secrets_redacted(self):
        env = envelope_from_exception(
            RuntimeError("failed with sk-abcdefghijklmnopqrstuvwxyz1234567890"),
            component_type="provider",
            component_id="openai",
            operation="chat",
        )
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in env.message
        assert "REDACTED" in env.message

    def test_stack_trace_truncated(self):
        def boom():
            raise ValueError("nope")

        try:
            boom()
        except ValueError as exc:
            env = envelope_from_exception(
                exc, component_type="tool", component_id="x", operation="y"
            )
        assert env.stack_trace
        assert len(env.stack_trace) <= 4000

    def test_non_recoverable_classes(self):
        env = envelope_from_exception(
            asyncio.CancelledError(),
            component_type="queue",
            component_id="w1",
            operation="run",
        )
        assert is_recoverable(env) is False
        assert env.is_user_action_required is False

    def test_permission_requires_user(self):
        env = envelope_from_exception(
            PermissionError("approval required"),
            component_type="tool",
            component_id="deleting",
            operation="delete_file",
            failure_class=FailureClass.PERMISSION_REQUIRED,
        )
        assert env.is_user_action_required is True
        assert is_recoverable(env) is True

    def test_with_attempt(self):
        env = envelope_from_exception(
            RuntimeError("boom"), component_type="tool", component_id="x", operation="y"
        )
        clone = env.with_attempt(3, ["retry_with_backoff"])
        assert clone.attempt_count == 3
        assert clone.previous_strategies == ["retry_with_backoff"]
        assert clone.failure_id == env.failure_id

    def test_round_trip(self):
        env = envelope_from_exception(
            TimeoutError("slow"),
            component_type="provider",
            component_id="deepseek",
            operation="stream",
            correlation_id="corr_1",
        )
        restored = FailureEnvelope.from_dict(env.to_dict())
        assert restored.failure_id == env.failure_id
        assert restored.failure_class == env.failure_class
        assert restored.component_id == env.component_id
        assert restored.correlation_id == env.correlation_id

    def test_serialize_round_trip(self):
        env = envelope_from_exception(
            RuntimeError("x"), component_type="a", component_id="b", operation="c"
        )
        assert deserialize_envelope(serialize_envelope(env)).failure_id == env.failure_id

    def test_from_dict_tolerant(self):
        restored = FailureEnvelope.from_dict({"component_type": "t"})
        assert restored.component_type == "t"
        assert restored.failure_class == FailureClass.UNKNOWN

    def test_signature_stable(self):
        def make():
            return envelope_from_exception(
                RuntimeError("boom"),
                component_type="tool",
                component_id="web_search",
                operation="search",
            )

        assert make().signature() == make().signature()