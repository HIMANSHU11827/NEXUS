from gateway.delivery import DeliveryLedger


def test_delivery_ledger_is_idempotent_and_restart_recoverable(tmp_path):
    db = str(tmp_path / "delivery.sqlite3")
    first = DeliveryLedger(db_path=db)
    a = first.enqueue(idempotency_key="event:1", platform="telegram", chat_id="c", text="hello")
    assert first.enqueue(idempotency_key="event:1", platform="telegram", chat_id="c", text="duplicate")["delivery_id"] == a["delivery_id"]
    claimed = first.claim("worker-a", platforms=["telegram"], lease_seconds=1)
    assert [item["delivery_id"] for item in claimed] == [a["delivery_id"]]

    second = DeliveryLedger(db_path=db)
    assert second.claim("worker-b", platforms=["telegram"]) == []
    assert second.ack(a["delivery_id"], "worker-b") is False
    assert second.fail(a["delivery_id"], "worker-a", "network") is True
    reclaimed = second.claim("worker-b", platforms=["telegram"])
    assert reclaimed[0]["delivery_id"] == a["delivery_id"]
    assert second.ack(a["delivery_id"], "worker-b", "remote-1") is True
    assert second.get(a["delivery_id"])["status"] == "sent"


def test_expired_leased_delivery_is_reclaimed_after_worker_crash(tmp_path):
    import time

    ledger = DeliveryLedger(db_path=str(tmp_path / "crashed-delivery.sqlite3"))
    item = ledger.enqueue(
        idempotency_key="event:crashed",
        platform="telegram",
        chat_id="c",
        text="recover me",
    )
    first = ledger.claim("dead-worker", platforms=["telegram"], lease_seconds=1)
    assert first and first[0]["delivery_id"] == item["delivery_id"]

    time.sleep(1.05)
    recovered = ledger.claim("recovery-worker", platforms=["telegram"], lease_seconds=10)

    assert recovered and recovered[0]["delivery_id"] == item["delivery_id"]
    assert recovered[0]["lease_owner"] == "recovery-worker"


def test_active_delivery_lease_can_be_renewed_without_changing_owner(tmp_path):
    ledger = DeliveryLedger(db_path=str(tmp_path / "renew-delivery.sqlite3"))
    item = ledger.enqueue(
        idempotency_key="event:renew",
        platform="telegram",
        chat_id="c",
        text="keep me",
    )
    claimed = ledger.claim("worker-a", platforms=["telegram"], lease_seconds=1)
    assert claimed and claimed[0]["lease_owner"] == "worker-a"
    assert ledger.renew(item["delivery_id"], "worker-a", lease_seconds=10) is True
    renewed = ledger.get(item["delivery_id"])
    assert renewed["lease_owner"] == "worker-a"
    assert renewed["lease_until"] > claimed[0]["lease_until"]
    assert ledger.renew(item["delivery_id"], "worker-b", lease_seconds=10) is False


def test_expired_owner_cannot_renew_ack_or_fail_before_reclaim(tmp_path):
    import time

    ledger = DeliveryLedger(db_path=str(tmp_path / "expired-owner.sqlite3"))
    item = ledger.enqueue(
        idempotency_key="event:expired-owner",
        platform="telegram",
        chat_id="c",
        text="lease expires",
    )
    claimed = ledger.claim("worker-a", platforms=["telegram"], lease_seconds=1)
    assert claimed
    time.sleep(1.05)

    assert ledger.renew(item["delivery_id"], "worker-a", lease_seconds=10) is False
    assert ledger.ack(item["delivery_id"], "worker-a") is False
    assert ledger.fail(item["delivery_id"], "worker-a", "stale") is False


def test_gateway_runner_persists_response_before_send(monkeypatch, tmp_path):
    import asyncio
    import gateway.run as gateway_run
    from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

    class Adapter(BasePlatformAdapter):
        def __init__(self):
            super().__init__("telegram")
            self.sent = []

        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def send_text(self, chat_id, text, reply_to=None):
            self.sent.append(text)
            return SendResult(success=True, message_id="m1")

        async def send_typing(self, chat_id):
            return None

    class Loop:
        root = str(tmp_path)

        def __init__(self, root_dir=None):
            if root_dir:
                self.root = root_dir

        def load_memory(self, _session):
            return None

        async def stream_run(self, _text, deadline_seconds=None):
            yield {"type": "content", "data": "answer"}

    monkeypatch.setattr(gateway_run, "NexusLoop", Loop)
    monkeypatch.setattr("authentication.is_gateway_authorized", lambda *_args: True)
    monkeypatch.setattr("utils.session_bus.set_active_session_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("utils.session_bus.sync_loop_from_disk", lambda *_args, **_kwargs: None)

    adapter = Adapter()
    runner = gateway_run.GatewayRunner(root=str(tmp_path))
    runner.add_adapter(adapter)
    event = MessageEvent(text="hi", sender_id="u", chat_id="c", platform="telegram", message_id="msg-1")
    asyncio.run(runner.handle_message(event))
    assert adapter.sent == ["answer"]
    assert runner._delivery_ledger.pending() == []


def test_gateway_runner_renews_lease_during_slow_send(tmp_path):
    import asyncio
    from gateway.base import BasePlatformAdapter, SendResult
    from gateway.run import GatewayRunner

    class SlowAdapter(BasePlatformAdapter):
        def __init__(self):
            super().__init__("telegram")

        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def send_text(self, chat_id, text, reply_to=None):
            await asyncio.sleep(1.3)
            return SendResult(success=True, message_id="slow-1")

    async def scenario():
        runner = GatewayRunner(root=str(tmp_path))
        runner.DELIVERY_LEASE_SECONDS = 1.0
        adapter = SlowAdapter()
        runner.add_adapter(adapter)
        item = runner._delivery_ledger.enqueue(
            idempotency_key="event:slow-send",
            platform="telegram",
            chat_id="c",
            text="slow",
        )
        drain = asyncio.create_task(runner._drain_deliveries())
        await asyncio.sleep(1.05)
        competing = runner._delivery_ledger.claim(
            "other-worker", platforms=["telegram"], lease_seconds=5
        )
        await drain
        assert competing == []
        assert runner._delivery_ledger.get(item["delivery_id"])["status"] == "sent"

    asyncio.run(scenario())


def test_permanent_delivery_failure_notifies_user(tmp_path):
    """Regression: a delivery that exhausts its attempts must be surfaced (P11)."""
    import asyncio
    from gateway.base import BasePlatformAdapter, SendResult
    from gateway.run import GatewayRunner

    class FailingAdapter(BasePlatformAdapter):
        def __init__(self):
            super().__init__("telegram")
            self.sent = []

        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def send_text(self, chat_id, text, reply_to=None):
            self.sent.append(text)
            return SendResult(success=False, error="rate limited")

    async def scenario():
        runner = GatewayRunner(root=str(tmp_path))
        adapter = FailingAdapter()
        runner.add_adapter(adapter)
        item = runner._delivery_ledger.enqueue(
            idempotency_key="event:doomed",
            platform="telegram",
            chat_id="c",
            text="lost message",
        )
        for _ in range(8):
            claimed = runner._delivery_ledger.claim(
                "worker", platforms=["telegram"], lease_seconds=5
            )
            assert claimed
            runner._delivery_ledger.fail(claimed[0]["delivery_id"], "worker", "rate limited")
        assert runner._delivery_ledger.get(item["delivery_id"])["status"] == "failed"

        await runner._notify_permanent_delivery_failure(item, adapter, "rate limited")

        assert any("could not be delivered" in text for text in adapter.sent)

    asyncio.run(scenario())
