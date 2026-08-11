"""Lifecycle tests for the supervised NEXUS gateway redesign.

Covers :class:`gateway.supervisor.GatewaySupervisor` and
:class:`gateway.supervisor.PlatformRuntime`:

* ``register_all`` starts only env-gated platforms,
* a failed adapter transitions ``connecting -> recovering`` with exponential
  backoff, then recovers once ``connect`` succeeds,
* a crash-looping adapter is ``disabled`` after N restarts instead of spinning,
* lifecycle state is persisted to the state file and reloaded honouring
  ``disabled_until``,
* ``stop_all`` disconnects gracefully and flushes final state.

Every test monkeypatches ``adapter.connect`` / ``adapter.disconnect`` and env —
no real network or credentials are used.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import gateway.supervisor as sup
from gateway.base import (
    HEALTH_DISABLED,
    HEALTH_HEALTHY,
    HEALTH_UNAVAILABLE,
    STATE_CONNECTING,
    STATE_DISABLED,
    STATE_RECOVERING,
    STATE_RUNNING,
    STATE_STOPPED,
    BasePlatformAdapter,
    SendResult,
)
from gateway.supervisor import GatewaySupervisor, PlatformRuntime
from gateway.delivery import DeliveryLedger
from gateway.run import GatewayRunner

# Fast timing so backoff / shutdown are test-friendly but still exercise the
# same exponential-backoff and crash-loop paths as production defaults.
FAST_CONFIG = {
    "backoff_base": 0.05,
    "backoff_cap": 0.10,
    "max_restarts": 5,
    "crash_window": 60.0,
    "disabled_cooldown": 60.0,
    "tick_interval": 0.01,
    "shutdown_timeout": 1.0,
}


async def test_supervisor_starts_and_stops_durable_delivery_worker(tmp_path):
    class Runner:
        def __init__(self):
            self.started = False
            self.stopped = False

        def add_adapter(self, _adapter):
            return None

        def start_delivery_loop(self):
            self.started = True

        async def stop_delivery_loop(self):
            self.stopped = True

    runner = Runner()
    supervisor = GatewaySupervisor(
        config=FAST_CONFIG,
        state_file=str(tmp_path / "state.json"),
        runner=runner,
    )
    supervisor.register_runtime(FakeAdapter("test"))
    await supervisor.start_all()
    assert runner.started is True
    await supervisor.stop_all()
    assert runner.stopped is True


async def test_supervisor_redacts_adapter_connect_errors():
    class SecretFailAdapter(FakeAdapter):
        async def connect(self) -> bool:
            raise RuntimeError("provider URL contains sk-secret-value")

    adapter = SecretFailAdapter("secret")
    runtime = PlatformRuntime(adapter, FAST_CONFIG)
    await runtime.connect_once(now=100.0)

    assert runtime.last_error is not None
    assert "sk-secret-value" not in runtime.last_error


async def test_supervisor_delivery_worker_drains_restart_queue(tmp_path):
    ledger = DeliveryLedger(db_path=str(tmp_path / "delivery.sqlite3"))
    runner = GatewayRunner(delivery_ledger=ledger)
    runner.DELIVERY_LOOP_INTERVAL_SECONDS = 0.01
    adapter = FakeAdapter("telegram")
    runner.add_adapter(adapter)
    supervisor = GatewaySupervisor(
        config=FAST_CONFIG,
        state_file=str(tmp_path / "state.json"),
        runner=runner,
    )
    supervisor.register_runtime(adapter)
    item = ledger.enqueue(
        idempotency_key="restart-response-1",
        platform="telegram",
        chat_id="chat",
        text="queued after restart",
    )

    await supervisor.start_all()
    try:
        for _ in range(20):
            if ledger.get(item["delivery_id"])["status"] == "sent":
                break
            await asyncio.sleep(0.01)
        assert ledger.get(item["delivery_id"])["status"] == "sent"
    finally:
        await supervisor.stop_all()


class FakeAdapter(BasePlatformAdapter):
    """Adapter whose connect results are scripted; no network anywhere."""

    def __init__(self, platform: str, connect_results=None):
        super().__init__(platform)
        self._connect_results = list(connect_results or [])
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> bool:
        self.connect_calls += 1
        if self._connect_results:
            return bool(self._connect_results.pop(0))
        return False

    async def disconnect(self):
        self.disconnect_calls += 1

    async def send_text(self, chat_id: str, text: str, reply_to=None) -> SendResult:
        return SendResult(success=True)


# --------------------------------------------------------------------------- #
# Env-gated registration
# --------------------------------------------------------------------------- #
def test_supervisor_registers_only_env_gated_platforms(monkeypatch, tmp_path):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN",
                "DISCORD_BOT_TOKEN", "DISCORD_TOKEN",
                "SLACK_BOT_TOKEN", "SLACK_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    monkeypatch.setattr(sup, "all_adapters", lambda: ["telegram", "discord", "slack"])
    monkeypatch.setattr(sup, "get_adapter", lambda p: FakeAdapter(p))

    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=str(tmp_path / "state.json"))
    sv.register_all()

    assert sorted(sv.adapters) == ["telegram"]
    assert "telegram" in sv.runtimes
    assert "discord" not in sv.runtimes
    assert "slack" not in sv.runtimes


def test_supervisor_registers_nothing_without_env(monkeypatch, tmp_path):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN",
                "DISCORD_BOT_TOKEN", "DISCORD_TOKEN",
                "SLACK_BOT_TOKEN", "SLACK_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sup, "all_adapters", lambda: ["telegram", "discord", "slack"])
    monkeypatch.setattr(sup, "get_adapter", lambda p: FakeAdapter(p))

    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=str(tmp_path / "state.json"))
    sv.register_all()

    assert sv.adapters == {}


# --------------------------------------------------------------------------- #
# Reconnecting: connecting -> recovering (backoff) -> running
# --------------------------------------------------------------------------- #
async def test_failed_adapter_transitions_to_recovering_then_recovers(tmp_path):
    adapter = FakeAdapter("telegram", connect_results=[False, False, True])
    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=str(tmp_path / "state.json"))
    sv.register_runtime(adapter)

    await sv.start_all()
    # start_all arms the first connect; the adapter is petitioned to connect.
    assert adapter.state == STATE_CONNECTING

    # First tick: connect fails -> recovering + unavailable with backoff.
    await sv._tick_once()
    assert adapter.state == STATE_RECOVERING
    assert adapter.health == HEALTH_UNAVAILABLE
    assert adapter.connect_calls == 1
    assert adapter.last_error == "telegram connect returned False"

    # An immediate tick must respect the backoff and not retry.
    await sv._tick_once()
    assert adapter.connect_calls == 1

    # Wait out the backoff; next attempts keep failing until the scripted
    # success, at which point the adapter is running/healthy and retries halt.
    for _ in range(30):
        await asyncio.sleep(0.06)
        await sv._tick_once()
        if adapter.state == STATE_RUNNING:
            break

    assert adapter.state == STATE_RUNNING
    assert adapter.health == HEALTH_HEALTHY
    assert adapter.connect_calls == 3  # exactly the consumed script
    assert adapter.restarts == 0

    await sv.stop_all()


# --------------------------------------------------------------------------- #
# Crash-loop detection
# --------------------------------------------------------------------------- #
async def test_crash_loop_disables_after_n_restarts(tmp_path):
    config = dict(FAST_CONFIG)
    config["max_restarts"] = 3
    adapter = FakeAdapter("telegram", connect_results=[])  # always False
    sv = GatewaySupervisor(config=config, state_file=str(tmp_path / "state.json"))
    sv.register_runtime(adapter)

    await sv.start_all()
    for _ in range(30):
        await sv._tick_once()
        await asyncio.sleep(0.06)
        if adapter.state == STATE_DISABLED:
            break

    assert adapter.state == STATE_DISABLED
    assert adapter.health == HEALTH_DISABLED
    assert adapter.restarts == 3
    assert adapter.paused_reason is not None
    assert "crash-loop" in adapter.paused_reason
    assert adapter.connect_calls == 3

    # A disabled platform must not keep reconnecting (no endless spin).
    calls_after_disable = adapter.connect_calls
    await asyncio.sleep(0.15)
    await sv._tick_once()
    assert adapter.connect_calls == calls_after_disable

    await sv.stop_all()


# --------------------------------------------------------------------------- #
# Persistence + reload honouring disabled_until
# --------------------------------------------------------------------------- #
async def test_state_persisted_and_reloaded_honoring_disabled_until(tmp_path):
    state_file = str(tmp_path / "state.json")
    config = dict(FAST_CONFIG)
    config["max_restarts"] = 2

    # Crash-loop the first supervisor into the disabled state.
    adapter = FakeAdapter("telegram", connect_results=[])
    sv1 = GatewaySupervisor(config=config, state_file=state_file)
    sv1.register_runtime(adapter)
    await sv1.start_all()
    for _ in range(30):
        await sv1._tick_once()
        await asyncio.sleep(0.06)
        if adapter.state == STATE_DISABLED:
            break
    assert adapter.state == STATE_DISABLED
    await sv1.stop_all()  # flush final state (disability must survive stop)

    persisted = json.loads(Path(state_file).read_text(encoding="utf-8"))
    entry = persisted["platforms"]["telegram"]
    assert entry["state"] == STATE_DISABLED
    assert entry["disabled_until"] > 0

    # Reload with an adapter that *would* connect: it must stay disabled until
    # the cooldown lapses.
    adapter2 = FakeAdapter("telegram", connect_results=[True])
    sv2 = GatewaySupervisor(config=FAST_CONFIG, state_file=state_file)
    sv2.register_runtime(adapter2)
    await sv2.start_all()
    assert adapter2.state == STATE_DISABLED
    await sv2._tick_once()
    assert adapter2.connect_calls == 0
    await sv2.stop_all()


# --------------------------------------------------------------------------- #
# Graceful shutdown
# --------------------------------------------------------------------------- #
async def test_stop_all_disconnects_gracefully(tmp_path):
    adapter = FakeAdapter("telegram", connect_results=[True])
    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=str(tmp_path / "state.json"))
    sv.register_runtime(adapter)

    await sv.start_all()
    await sv._tick_once()
    assert adapter.state == STATE_RUNNING
    assert adapter.health == HEALTH_HEALTHY

    await sv.stop_all()
    assert adapter.disconnect_calls == 1
    assert adapter.state == STATE_STOPPED
    assert adapter.health == HEALTH_UNAVAILABLE

    # stop_all is idempotent.
    await sv.stop_all()
    assert adapter.state == STATE_STOPPED


async def test_overlapping_manual_ticks_do_not_double_connect(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAdapter(FakeAdapter):
        async def connect(self) -> bool:
            self.connect_calls += 1
            started.set()
            await release.wait()
            return True

    adapter = SlowAdapter("telegram")
    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=str(tmp_path / "state.json"))
    sv.register_runtime(adapter)
    await sv.start_all()

    first = asyncio.create_task(sv._tick_once())
    await asyncio.wait_for(started.wait(), timeout=1)
    second = asyncio.create_task(sv._tick_once())
    await asyncio.sleep(0)
    assert adapter.connect_calls == 1

    release.set()
    await asyncio.gather(first, second)
    assert adapter.connect_calls == 1
    assert adapter.state == STATE_RUNNING
    await sv.stop_all()


async def test_shutdown_waits_for_inflight_connect_before_persisting_stopped(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAdapter(FakeAdapter):
        async def connect(self) -> bool:
            self.connect_calls += 1
            started.set()
            await release.wait()
            return True

    adapter = SlowAdapter("telegram")
    state_file = str(tmp_path / "state.json")
    sv = GatewaySupervisor(config=FAST_CONFIG, state_file=state_file)
    sv.register_runtime(adapter)
    await sv.start_all()

    tick = asyncio.create_task(sv._tick_once())
    await asyncio.wait_for(started.wait(), timeout=1)
    stopping = asyncio.create_task(sv.stop_all())
    await asyncio.sleep(0)
    assert not stopping.done()

    release.set()
    await asyncio.gather(tick, stopping)
    assert adapter.state == STATE_STOPPED
    persisted = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert persisted["platforms"]["telegram"]["state"] == STATE_STOPPED


# --------------------------------------------------------------------------- #
# Shared reconnect helper
# --------------------------------------------------------------------------- #
async def test_guard_poll_reconnects_with_backoff():
    """The shared base helper re-arms a failing poll instead of dying."""
    adapter = FakeAdapter("line", connect_results=[])
    calls = []

    async def flaky_poll():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")

    task = asyncio.create_task(
        adapter._guard_poll(flaky_poll, backoff_base=0.01, backoff_cap=0.02)
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.02)
            if len(calls) >= 4:
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(calls) >= 3
    assert adapter.health == HEALTH_HEALTHY  # recovered after the flaky pings
