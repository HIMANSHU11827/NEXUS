"""Redesign tests for the NEXUS reliability / 24-7 layer.

Covers the fatigue-proofing work in ``queue/driver.py``, ``queue/store.py``,
``gateway/run.py``, ``gateway/webhook_server.py``, ``gateway/platforms/
telegram.py`` and ``providers/{reliability,health}.py``:

* startup lease-reap sweep on worker start
* ``ack_lease`` renewal of long-running task leases
* telegram ``infinity_polling`` re-armed with exponential backoff
* ingress message-id dedupe (LRU, TTL-bounded) in gateway + webhook paths
* bounded retry for tool/gateway work (`call_with_reliability` /
  ``bounded_tool_retry``) with provider-form regression coverage
* per-component circuit breaker registry
"""

from __future__ import annotations

import asyncio
import time

import pytest

import gateways.webhook_server as webhook_server
from gateways.base import BasePlatformAdapter, MessageEvent, SendResult
from gateways.platforms.telegram import TelegramAdapter
from gateways.run import GatewayRunner, IngressDedupe, dedupe_key_for_event
from providers.health import ComponentBreakerRegistry
from providers.reliability import (
    BreakerState,
    FailureClass,
    ProviderCallError,
    RetryPolicy,
    bounded_tool_retry,
    call_with_reliability,
    classify_failure,
)
from queues.driver import QueueDriver
from queues.store import TaskQueue


def test_billing_and_quota_failures_do_not_retry_like_transient_rate_limits():
    billing = classify_failure(body="402 payment required: credits exhausted")
    quota = classify_failure(body="429 quota exceeded for this project")
    rate_limit = classify_failure(body="429 too many requests; retry later")

    assert billing.failure_class is FailureClass.BILLING_QUOTA
    assert billing.retryable is False
    assert billing.strategy.value == "fallback_provider"
    assert quota.failure_class is FailureClass.BILLING_QUOTA
    assert quota.retryable is False
    assert rate_limit.failure_class is FailureClass.RATE_LIMIT
    assert rate_limit.retryable is True


# --------------------------------------------------------------------------- #
# 1. Startup lease-reap sweep
# --------------------------------------------------------------------------- #
async def test_startup_lease_reap_called_on_worker_start():
    reaps: list[str] = []

    class FakeQueue:
        def requeue_expired_leases(self):
            reaps.append("reap")
            return 2  # two crashed leases immediately re-enqueued

        def lease(self, timeout_sec=None, worker_id=""):
            return None

        def complete(self, *_a, **_k):
            return True

        def fail(self, *_a, **_k):
            return True

    driver = QueueDriver(queue=FakeQueue(), idle_sleep=0.01)
    worker_task = asyncio.ensure_future(driver._worker("w1"))
    await asyncio.sleep(0.05)
    driver.stop()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert reaps == ["reap"]            # crash sweep ran exactly once at boot
    assert driver._startup_reap_done is True


# --------------------------------------------------------------------------- #
# 2. Lease renewal
# --------------------------------------------------------------------------- #
def test_ack_lease_renews_lease_expiry(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "ack.db"))
    task_id = queue.enqueue("long running task", max_attempts=3)
    leased = queue.lease(timeout_sec=120, worker_id="w1")
    token = leased["lease_token"]
    original_until = queue.get(task_id)["leased_until"]

    # Pure ownership check (no timeout) must not move leased_until.
    assert queue.ack_lease(task_id, token) is True
    unchanged = queue.get(task_id)["leased_until"]
    assert abs(unchanged - original_until) < 0.05

    # Renewal pushes leased_until forward.
    assert queue.ack_lease(task_id, token, timeout_sec=120) is True
    assert queue.get(task_id)["leased_until"] > original_until

    # A stale token can never confirm/renew.
    assert queue.ack_lease(task_id, "bogus-token", timeout_sec=120) is False
    assert queue.ack_lease(task_id, token) is True  # real worker still owns it


async def test_long_running_worker_renews_lease_mid_task(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "heartbeat.db"))
    task_id = queue.enqueue("slow turn", max_attempts=3)
    leased = queue.lease(timeout_sec=2, worker_id="w1")
    token = leased["lease_token"]
    original_until = queue.get(task_id)["leased_until"]

    class Loop:
        async def stream_run(self, task_desc, **kwargs):
            await asyncio.sleep(1.5)  # outlives TTL/2 (1.0s at lease_timeout=2)
            yield {"type": "done", "data": {"success": True, "response": "ok"}}

    class Kernel:
        root = "."
        loop = Loop()

    driver = QueueDriver(queue=queue, kernel=Kernel(), lease_timeout=2)
    result = await driver._run_with_heartbeat(
        leased, task_id=task_id, lease_token=token, leased_at=time.time()
    )
    assert result == "ok"
    assert queue.get(task_id)["leased_until"] > original_until


# --------------------------------------------------------------------------- #
# 3. Telegram poll backoff re-arm
# --------------------------------------------------------------------------- #
async def test_telegram_poll_backoff_reams_after_failure():
    adapter = TelegramAdapter(token="test-token")
    adapter._disconnecting = False
    adapter._poll_backoff_base = 0.01
    adapter._poll_backoff_cap = 60.0

    calls = {"n": 0}

    class FakeBot:
        async def infinity_polling(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("long poll failed")
            while not adapter._disconnecting:
                await asyncio.sleep(0.005)

    adapter.bot = FakeBot()

    poll_task = asyncio.ensure_future(adapter._safe_poll())
    await asyncio.sleep(0.15)  # fail -> back off -> re-arm
    assert calls["n"] >= 2, "poll loop must re-arm after the first failure"

    adapter._disconnecting = True
    await poll_task  # graceful exit, no CancelledError leakage


# --------------------------------------------------------------------------- #
# 4. Message-id ingress dedupe
# --------------------------------------------------------------------------- #
def test_ingress_dedupe_skips_duplicates_allows_new():
    dedupe = IngressDedupe(max_size=1000, ttl=600.0)
    assert dedupe.seen("telegram:msg:1") is False
    assert dedupe.seen("telegram:msg:1") is True     # repeat within TTL -> drop
    assert dedupe.seen("telegram:msg:2") is False    # new id allowed
    assert dedupe.seen("other:hash:abc") is False
    assert dedupe.seen("other:hash:abc") is True

    # TTL expiry frees the key for reuse.
    future = time.time() + 601.0
    assert dedupe.seen("telegram:msg:1", now=future) is False


def test_dedupe_key_prefers_message_id_and_hashes_fallback():
    with_id = MessageEvent(
        text="hi", sender_id="s", chat_id="c", platform="telegram", message_id="42"
    )
    assert dedupe_key_for_event(with_id) == "telegram:msg:42"

    no_id = MessageEvent(
        text="hi", sender_id="s", chat_id="c", platform="telegram", message_id=None
    )
    key = dedupe_key_for_event(no_id)
    assert key.startswith("telegram:hash:")
    assert dedupe_key_for_event(no_id) == key  # stable within the session


class _FakeAdapter(BasePlatformAdapter):
    def __init__(self, platform: str = "telegram"):
        super().__init__(platform)
        self.sent: list[str] = []
        self.typing_calls = 0

    async def connect(self) -> bool:
        return True

    async def disconnect(self):
        return None

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> SendResult:
        self.sent.append(text)
        return SendResult(success=True)

    async def send_typing(self, chat_id: str):
        self.typing_calls += 1


async def test_handle_message_skips_duplicate_message_ids(monkeypatch, tmp_path):
    import gateways.run as gateway_run
    from gateways.delivery import DeliveryLedger
    from utils import session_bus

    class FakeLoop:
        root = "C:\\project"

        def __init__(self, root_dir=None):
            if root_dir:
                self.root = root_dir

        def load_memory(self, session_id):
            self.session_id = session_id

        async def stream_run(self, text, deadline_seconds=None):
            yield {"type": "content", "data": "pong"}

    monkeypatch.setattr(gateway_run, "NexusLoop", FakeLoop)
    monkeypatch.setattr(
        gateway_run, "set_active_session_id", lambda *_a, **_k: None, raising=False
    )
    monkeypatch.setattr(session_bus, "set_active_session_id", lambda *_a, **_k: None)
    monkeypatch.setattr(session_bus, "sync_loop_from_disk", lambda _loop: None)
    monkeypatch.setattr("authentication.is_gateway_authorized", lambda *_a: True)

    gateway_run.ingress_dedupe.clear()

    runner = GatewayRunner(delivery_ledger=DeliveryLedger(db_path=str(tmp_path / "delivery.sqlite3")))
    adapter = _FakeAdapter("telegram")
    runner.add_adapter(adapter)

    first = MessageEvent(
        text="hi", sender_id="u", chat_id="c", platform="telegram", message_id="100"
    )
    await runner.handle_message(first)
    assert adapter.sent == ["pong"]

    await runner.handle_message(first)  # same message_id -> dropped
    assert adapter.sent == ["pong"], "duplicate delivery must be skipped"

    second = MessageEvent(
        text="hi", sender_id="u", chat_id="c", platform="telegram", message_id="101"
    )
    await runner.handle_message(second)  # new message_id -> allowed
    assert adapter.sent == ["pong", "pong"]


async def test_webhook_dispatch_dedupes_duplicate_event():
    from gateways.run import ingress_dedupe
    from gateways.base import MessageEvent

    ingress_dedupe.clear()
    received: list[MessageEvent] = []

    class FakeAdapter:
        platform = "test"

        def __init__(self, handler):
            self._on_message = handler

    adapter = FakeAdapter(lambda ev: received.append(ev))
    first = MessageEvent(
        text="hi", sender_id="s", chat_id="c", platform="test", message_id="w1"
    )
    await webhook_server._dispatch_event(adapter, first)
    assert len(received) == 1

    # A real redelivery arrives as a NEW object carrying the same message_id.
    redelivery = MessageEvent(
        text="hi", sender_id="s", chat_id="c", platform="test", message_id="w1"
    )
    await webhook_server._dispatch_event(adapter, redelivery)
    assert len(received) == 1

    second = MessageEvent(
        text="hi", sender_id="s", chat_id="c", platform="test", message_id="w2"
    )
    await webhook_server._dispatch_event(adapter, second)
    assert len(received) == 2


# --------------------------------------------------------------------------- #
# 5. Bounded retry for tool/gateway work
# --------------------------------------------------------------------------- #
def test_bounded_tool_retry_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = bounded_tool_retry(flaky, retry_policy=2)
    assert result == "ok"
    assert calls["n"] == 3  # 2 retries + initial attempt


async def test_bounded_tool_retry_async_retries():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = await bounded_tool_retry(flaky, retry_policy=2)
    assert result == "ok"
    assert calls["n"] == 3


def test_bounded_tool_retry_raises_after_retries_exhausted():
    def always_fails():
        raise ConnectionError("down")

    with pytest.raises(ProviderCallError):
        bounded_tool_retry(always_fails, retry_policy=1)


def test_call_with_reliability_provider_form_preserved():
    calls = {"n": 0}

    def generate(messages=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderCallError(classify_failure(body="temporary outage"), "prov")
        return "response"

    policy = RetryPolicy(max_attempts=2, base_delay=0.01, jitter=0.0)
    result = call_with_reliability("prov", generate, messages=[], policy=policy)
    assert result == "response"
    assert calls["n"] == 2


async def test_call_with_reliability_preserves_async_cancellation():
    calls = {"n": 0}

    async def cancelled():
        calls["n"] += 1
        raise asyncio.CancelledError("operator stopped provider call")

    with pytest.raises(asyncio.CancelledError, match="operator stopped"):
        await call_with_reliability(
            "prov",
            cancelled,
            policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=0.0),
        )
    assert calls["n"] == 1


async def test_call_with_reliability_awaits_async_callable_instances():
    class AsyncCallable:
        async def __call__(self):
            return "ok"

    result = await call_with_reliability(
        AsyncCallable(),
        retry_policy=RetryPolicy(max_attempts=1, base_delay=0),
    )
    assert result == "ok"


# --------------------------------------------------------------------------- #
# 6. Per-component circuit breaker
# --------------------------------------------------------------------------- #
def test_component_breaker_opens_and_closes():
    registry = ComponentBreakerRegistry(failure_threshold=3, cooldown=30.0)

    # "tools" is preseeded empty and starts closed.
    assert "tools" in registry.snapshot()
    assert registry.is_open("tools") is False

    breaker = registry.get("tools")
    clock = {"t": 1000.0}
    breaker.set_clock(lambda: clock["t"])

    # Three consecutive failures trip the breaker open.
    for _ in range(3):
        registry.record_failure("tools")
    assert registry.is_open("tools") is True
    assert registry.allows("tools") is False
    assert registry.snapshot("tools")["state"] == BreakerState.OPEN.value

    # After the cooldown a half-open probe is allowed; success closes it.
    clock["t"] += 31.0
    assert registry.allows("tools") is True
    registry.record_success("tools")
    assert registry.is_open("tools") is False
    assert registry.allows("tools") is True

    # Storm again, then an explicit reset recovers.
    for _ in range(3):
        registry.record_failure("tools")
    assert registry.is_open("tools") is True
    registry.reset("tools")
    assert registry.is_open("tools") is False

    # Unseeded components are created lazily.
    assert registry.is_open("gateway:slack") is False
    registry.record_failure("gateway:slack")
    assert registry.is_open("gateway:slack") is False  # below threshold
