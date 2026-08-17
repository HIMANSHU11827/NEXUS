"""NEXUS Unified Gateway Supervisor.

Owns every registered platform adapter as a :class:`PlatformRuntime` and drives
a supervised, health-state-aware lifecycle instead of the fire-and-forget
``connect``/``disconnect`` of the legacy :class:`~gateway.run.GatewayRunner`.

* ``start_all`` registers only env-gated platforms and starts one supervised
  runtime per adapter, honouring previously persisted ``disabled`` state and
  ``disabled_until`` backoff.
* A periodic ``tick`` reconnects any adapter in ``recovering`` / ``unavailable``
  with exponential backoff (1s, 2s, 4s ... capped at 60s) and bounded restarts
  (max N per window) with crash-loop detection: once an adapter exceeds its
  restart budget it is ``disabled`` with a reason and a ``disabled_until``
  cooldown instead of spinning forever.
* Lifecycle state is persisted to ``~/.nexus/gateway/state.json`` (atomic write,
  never raises) and honoured on restart.
* ``stop_all`` cancels in-flight work and gracefully disconnects every adapter
  within a bounded timeout, then writes the final state.

Backward compatibility: the legacy ``GatewayRunner`` (gateway/run.py) is left
untouched and remains the drop-in for code that wants plain connect/disconnect.
Message routing is delegated to an internal ``GatewayRunner`` so the supervised
adapters feed the exact same session/loop pipeline as before.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Optional

from gateway.base import (
    BasePlatformAdapter,
    HEALTH_DISABLED,
    HEALTH_HEALTHY,
    HEALTH_UNAVAILABLE,
    STATE_CONNECTING,
    STATE_CREATED,
    STATE_DISABLED,
    STATE_RECOVERING,
    STATE_RUNNING,
    STATE_STOPPED,
)
from gateway.platforms import all_adapters, get_adapter
from gateway.run import GatewayRunner, _PLATFORM_ENV_MAP, _has_required_env
from gateway.state import GatewayStateStore
from providers.reliability import redact_secrets

logger = logging.getLogger(__name__)

# Default supervision policy. Operators may override per-runtime via config.
DEFAULT_CONFIG = {
    "backoff_base": 1.0,        # first reconnect delay (doubles up to cap)
    "backoff_cap": 60.0,        # max reconnect delay
    "connect_timeout": 30.0,    # hard deadline for one adapter connect attempt
    "max_restarts": 5,          # crash budget within the window
    "crash_window": 60.0,       # seconds over which restarts are counted
    "disabled_cooldown": 60.0,  # how long a crash-looping platform stays off
    "tick_interval": 1.0,       # supervisor tick cadence
    "shutdown_timeout": 10.0,   # max seconds to wait for disconnects on stop
}


class PlatformRuntime:
    """Supervised lifecycle wrapper around a single platform adapter.

    State flows ``created -> connecting -> running -> recovering -> stopped``
    (plus ``paused`` / ``disabled``). The supervisor fuels connect attempts from
    its periodic :meth:`GatewaySupervisor.tick`; the runtime owns the per-attempt
    outcome and the exponential-backoff / crash-loop bookkeeping. Lifecycle
    fields are mirrored onto ``adapter`` so ``adapter.state``, ``adapter.health``,
    ``adapter.last_error``, ``adapter.restarts`` and ``adapter.paused_reason``
    are always readable.
    """

    def __init__(self, adapter: BasePlatformAdapter, config: Optional[Dict] = None):
        self.adapter = adapter
        self.platform = getattr(adapter, "platform", type(adapter).__name__)
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self._init_adapter_state()
        self.backoff = float(self.config["backoff_base"])
        self.restarts = 0
        self._window_start = 0.0
        self.next_attempt_at = 0.0
        self.disabled_until = 0.0
        self.paused_reason: Optional[str] = None
        self.last_error: Optional[str] = None
        self._connect_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # State mirroring
    # ------------------------------------------------------------------ #
    def _init_adapter_state(self) -> None:
        """Ensure the adapter exposes the supervised lifecycle attributes."""
        a = self.adapter
        for attr, default in (
            ("state", STATE_CREATED),
            ("health", HEALTH_UNAVAILABLE),
            ("last_error", None),
            ("restarts", 0),
            ("paused_reason", None),
            ("disabled_until", 0.0),
        ):
            if not hasattr(a, attr):
                setattr(a, attr, default)

    @property
    def state(self) -> str:
        return getattr(self.adapter, "state", STATE_CREATED)

    @state.setter
    def state(self, value: str) -> None:
        self.adapter.state = value

    @property
    def health(self) -> str:
        return getattr(self.adapter, "health", HEALTH_UNAVAILABLE)

    @health.setter
    def health(self, value: str) -> None:
        self.adapter.health = value

    def _set_state(self, value: str) -> None:
        self.adapter.state = value

    def _set_health(self, value: str) -> None:
        self.adapter.health = value

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        """Return this runtime's lifecycle state for persistence."""
        return {
            "state": self.state,
            "health": self.health,
            "last_error": self.last_error,
            "restarts": self.restarts,
            "paused_reason": self.paused_reason,
            "disabled_until": self.disabled_until,
            "updated_at": time.time(),
        }

    def restore(self, data: Optional[dict]) -> None:
        """Apply persisted state on startup (honours ``disabled_until``)."""
        if not isinstance(data, dict):
            return
        self.disabled_until = float(data.get("disabled_until", 0.0) or 0.0)
        self.restarts = int(data.get("restarts", 0) or 0)
        self.paused_reason = data.get("paused_reason")
        self.last_error = data.get("last_error")
        if data.get("state") == STATE_DISABLED:
            self._set_state(STATE_DISABLED)
            self._set_health(HEALTH_DISABLED)
            self.paused_reason = self.paused_reason or "disabled on previous run"
        # Mirror the resurrected lifecycle fields onto the adapter so the same
        # attributes are readable before the first tick fires.
        self.adapter.restarts = self.restarts
        self.adapter.paused_reason = self.paused_reason
        self.adapter.last_error = self.last_error
        self.adapter.disabled_until = self.disabled_until
        # Any other past state collapses back to created; health is derived
        # from the next connect attempt.

    # ------------------------------------------------------------------ #
    # Connect / recover
    # ------------------------------------------------------------------ #
    @staticmethod
    def _consume_connect_result(task: asyncio.Task) -> None:
        """Retrieve a detached connect result so asyncio never logs it later."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("detached gateway connect task failed", exc_info=True)

    def cancel_connect(self) -> None:
        """Fence an in-flight connect without waiting on uncooperative code."""
        task = self._connect_task
        self._connect_task = None
        if task is None or task.done():
            return
        task.cancel()
        task.add_done_callback(self._consume_connect_result)

    async def connect_once(self, now: Optional[float] = None) -> None:
        """Perform a single connect attempt and record its outcome.

        Success → ``running``/``healthy`` and resets the restart budget. Failure
        → ``recovering``/``unavailable``, increments the restart count, doubles
        the backoff and schedules the next attempt at ``now + backoff``. If the
        restart budget is exhausted the runtime is ``disabled`` with a reason
        and a ``disabled_until`` cooldown (crash-loop detection).
        """
        if now is None:
            now = time.time()

        # A timed-out adapter may ignore cancellation. Never start a second
        # connect while that detached attempt is still alive; doing so can
        # create duplicate pollers or sockets for the same platform.
        previous = self._connect_task
        if previous is not None:
            if not previous.done():
                self._set_state(STATE_RECOVERING)
                self._set_health(HEALTH_UNAVAILABLE)
                self.last_error = self.last_error or f"{self.platform} previous connect attempt is still stopping"
                self.adapter.last_error = self.last_error
                return
            self._connect_task = None
            try:
                delayed_ok = bool(previous.result())
            except asyncio.CancelledError:
                delayed_ok = False
            except Exception as exc:
                self.last_error = redact_secrets(exc)
                delayed_ok = False
            if delayed_ok:
                self._record_success()
                return

        self._set_state(STATE_CONNECTING)
        self._set_health(HEALTH_UNAVAILABLE)
        self.last_error = None
        ok = False
        connect_task = asyncio.create_task(self.adapter.connect())
        self._connect_task = connect_task
        timeout = max(0.01, float(self.config.get("connect_timeout", 30.0)))
        try:
            done, _pending = await asyncio.wait((connect_task,), timeout=timeout)
            if not done:
                self.last_error = f"{self.platform} connect timed out after {timeout:.2f}s"
                connect_task.cancel()
                connect_task.add_done_callback(self._consume_connect_result)
            else:
                self._connect_task = None
                try:
                    ok = bool(connect_task.result())
                except asyncio.CancelledError:
                    self.last_error = f"{self.platform} connect was cancelled"
                    ok = False
                except Exception as exc:
                    self.last_error = redact_secrets(exc)
                    ok = False
        except asyncio.CancelledError:
            # Cancellation of the supervision pass must release the global
            # tick lock immediately, even if adapter code ignores cancellation.
            connect_task.cancel()
            connect_task.add_done_callback(self._consume_connect_result)
            raise
        except Exception as exc:  # a raising connect == a failed attempt
            self.last_error = redact_secrets(exc)
            ok = False
        if ok:
            self._record_success()
        else:
            self.last_error = self.last_error or f"{self.platform} connect returned False"
            self._record_failure(now)

    def _record_success(self) -> None:
        self.restarts = 0
        self._window_start = 0.0
        self.backoff = float(self.config["backoff_base"])
        self.next_attempt_at = 0.0
        self.last_error = None
        self.paused_reason = None
        self.disabled_until = 0.0
        self._set_state(STATE_RUNNING)
        self._set_health(HEALTH_HEALTHY)
        self.adapter.restarts = self.restarts  # mirrored reset
        self.adapter.last_error = None
        self.adapter.paused_reason = None
        self.adapter.disabled_until = 0.0
        logger.info("NEXUS %s adapter connected (healthy)", self.platform)

    def _record_failure(self, now: float) -> None:
        # Rolling window: restart count resets once the window elapses.
        if self.restarts == 0 or (now - self._window_start) > self.config["crash_window"]:
            self._window_start = now
            self.restarts = 1
        else:
            self.restarts += 1
        self.adapter.restarts = self.restarts

        # Crash-loop detection: exhausted budget -> disable, don't spin forever.
        if self.restarts >= int(self.config["max_restarts"]):
            self._disable(now)
            return

        self.backoff = min(self.backoff * 2, float(self.config["backoff_cap"]))
        self.next_attempt_at = now + self.backoff
        self._set_state(STATE_RECOVERING)
        self._set_health(HEALTH_UNAVAILABLE)
        self.adapter.last_error = self.last_error
        logger.warning(
            "NEXUS %s adapter failed to connect (%s); recovering in %.1fs "
            "(restart %d/%d)",
            self.platform, self.last_error or "error", self.backoff,
            self.restarts, self.config["max_restarts"],
        )

    def _disable(self, now: float) -> None:
        self.paused_reason = (
            f"crash-loop: {self.restarts} restarts in "
            f"{int(self.config['crash_window'])}s window"
        )
        self.disabled_until = now + float(self.config["disabled_cooldown"])
        self._set_state(STATE_DISABLED)
        self._set_health(HEALTH_DISABLED)
        self.adapter.paused_reason = self.paused_reason
        self.adapter.disabled_until = self.disabled_until
        logger.warning(
            "Disabling NEXUS %s adapter: %s (backoff until %.0f)",
            self.platform, self.paused_reason, self.disabled_until,
        )

    def _re_enable(self) -> None:
        """Transition out of a disabled cooldown so the tick can retry."""
        self.restarts = 0
        self._window_start = 0.0
        self.backoff = float(self.config["backoff_base"])
        self.disabled_until = 0.0
        self.paused_reason = None
        self._set_state(STATE_CREATED)
        self._set_health(HEALTH_UNAVAILABLE)
        self.adapter.paused_reason = None
        self.adapter.disabled_until = 0.0
        logger.info("NEXUS %s adapter cooldown expired; re-arming", self.platform)


class GatewaySupervisor:
    """Owns all platform runtimes and supervises their lifecycle.

    Message routing is delegated to an internal :class:`GatewayRunner` so the
    adapters feed the same per-chat session / NexusLoop pipeline as the legacy
    gateway. ``adapters`` remains a plain ``{platform: adapter}`` map so the
    webhook server and any other consumer keep working unchanged.
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        state_file: Optional[str] = None,
        runner: Optional[GatewayRunner] = None,
    ):
        self.config = dict(DEFAULT_CONFIG)
        env_connect_timeout = os.environ.get("NEXUS_GATEWAY_CONNECT_TIMEOUT", "").strip()
        if env_connect_timeout:
            try:
                self.config["connect_timeout"] = max(0.01, float(env_connect_timeout))
            except ValueError:
                logger.warning(
                    "ignoring invalid NEXUS_GATEWAY_CONNECT_TIMEOUT=%r",
                    env_connect_timeout,
                )
        if config:
            self.config.update(config)
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self.runtimes: Dict[str, PlatformRuntime] = {}
        self._store = GatewayStateStore(state_file)
        self._runner = runner or GatewayRunner()
        self._running = False
        self._stopping = False
        self._tick_task: Optional[asyncio.Task] = None
        # ``tick(once=True)`` is also a public diagnostic/recovery entry point.
        # Serialize it with the periodic loop so two callers cannot both see
        # the same runtime as restartable and invoke adapter.connect() twice.
        self._tick_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register_runtime(self, adapter: BasePlatformAdapter) -> PlatformRuntime:
        """Register a single adapter under a supervised runtime."""
        rt = PlatformRuntime(adapter, self.config)
        self.adapters[adapter.platform] = adapter
        self.runtimes[adapter.platform] = rt
        # Route messages through the shared runner's session/loop pipeline.
        self._runner.add_adapter(adapter)
        return rt

    def register_all(self) -> None:
        """Auto-discover and register every platform whose env vars are present."""
        for platform_name in all_adapters():
            required = _PLATFORM_ENV_MAP.get(platform_name, [])
            if required and not _has_required_env(required):
                logger.debug(f"Skipping {platform_name} — missing env vars {required}")
                continue
            try:
                adapter = get_adapter(platform_name)
                self.register_runtime(adapter)
                logger.info(f"Registered {platform_name} adapter")
            except Exception as e:  # degrade softly — bad adapter never blocks others
                logger.warning(f"Failed to register {platform_name}: {e}")

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start_all(self) -> None:
        """Arm registered runtimes without racing a tick or shutdown."""
        async with self._tick_lock:
            await self._start_all()

    async def _start_all(self) -> None:
        """Start one supervised runtime per registered, env-gated adapter.

        Loads persisted lifecycle state and honours ``disabled_until``: a
        platform disabled on a previous run stays off until its cooldown lapses.
        """
        saved = self._store.load()
        now = time.time()
        for name, rt in self.runtimes.items():
            rt.restore(saved.get(name, {}))
        self._stopping = False
        self._running = True
        start_delivery = getattr(self._runner, "start_delivery_loop", None)
        if callable(start_delivery):
            start_delivery()
        for name, rt in self.runtimes.items():
            if rt.state == STATE_DISABLED and rt.disabled_until > now:
                # Persisted crash-loop cooldown not yet elapsed — stay off.
                logger.info(
                    "NEXUS %s adapter held disabled until %.0f",
                    name, rt.disabled_until,
                )
                continue
            rt._set_state(STATE_CONNECTING)
            rt._set_health(HEALTH_UNAVAILABLE)
            rt.next_attempt_at = 0.0
        self._store.save(self._snapshot())
        logger.info("Gateway supervisor started %d platform(s)", len(self.runtimes))

    async def run(self) -> None:
        """Start all platforms and keep supervising until cancelled."""
        await self.start_all()
        self._tick_task = asyncio.create_task(self._tick_loop())
        try:
            await self._tick_task
        except asyncio.CancelledError:  # graceful stop via stop_all / signal
            pass

    async def tick(self, once: bool = False) -> None:
        """Run the supervision pass — a single ``_tick_once`` or forever."""
        if once:
            await self._tick_once()
            return
        self._tick_task = asyncio.create_task(self._tick_loop())
        try:
            await self._tick_task
        except asyncio.CancelledError:
            pass

    async def _tick_loop(self) -> None:
        while self._running:
            await self._tick_once()
            await asyncio.sleep(self.config["tick_interval"])

    async def _tick_once(self) -> None:
        async with self._tick_lock:
            now = time.time()
            # Snapshot the mapping before awaiting adapter work. Registration
            # from another task must not invalidate dictionary iteration.
            runtimes = tuple(self.runtimes.items())
            for name, rt in runtimes:
                try:
                    await self._supervise(rt, now)
                except Exception:  # one bad runtime must not take the loop down
                    logger.exception("gateway/supervisor.py tick error for %s", name)
            self._store.save(self._snapshot())

    async def _supervise(self, rt: PlatformRuntime, now: float) -> None:
        """Reconnect any runtime that is down, respecting backoff + crash budget."""
        if self._stopping:
            return
        # Disabled: wait out the cooldown, then re-arm.
        if rt.state == STATE_DISABLED:
            if rt.disabled_until and now >= rt.disabled_until:
                rt._re_enable()
            else:
                return
        # Healthy + running: nothing to do.
        if rt.state == STATE_RUNNING and rt.health == HEALTH_HEALTHY:
            return
        # Running but degraded (an internal poll loop reported itself down):
        # treat as needing a reconnect.
        if rt.state == STATE_RUNNING:
            rt._set_state(STATE_RECOVERING)
        # Only reconnect from a restartable state, and not during backoff.
        if rt.state not in (STATE_CREATED, STATE_CONNECTING, STATE_RECOVERING):
            return
        if now < rt.next_attempt_at:
            return
        await rt.connect_once(now)
        # A manual one-shot tick is not stored in ``_tick_task`` and may race
        # shutdown. Project the final state back to stopped after its bounded
        # connect returns so it cannot resurrect a stopped runtime.
        if self._stopping and rt.state != STATE_DISABLED:
            rt._set_state(STATE_STOPPED)
            rt._set_health(HEALTH_UNAVAILABLE)

    async def stop_all(self) -> None:
        """Stop every gateway component within the configured shutdown bound."""
        timeout = max(0.01, float(self.config["shutdown_timeout"]))
        self._stopping = True
        self._running = False

        # Cancel periodic supervision before taking the lock. Otherwise a
        # cancellation-resistant adapter connect can hold the lock forever and
        # prevent shutdown from even beginning.
        await self._cancel_tick_task(timeout)

        acquired = False
        try:
            await asyncio.wait_for(self._tick_lock.acquire(), timeout=timeout)
            acquired = True
        except asyncio.TimeoutError:
            logger.warning(
                "gateway supervisor lock did not settle within %.2fs; continuing bounded shutdown",
                timeout,
            )
        try:
            await self._stop_all(timeout=timeout)
        finally:
            if acquired:
                self._tick_lock.release()

    @staticmethod
    def _consume_detached_task(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("detached gateway shutdown task failed", exc_info=True)

    async def _await_bounded(self, awaitable, timeout: float, label: str) -> bool:
        """Await lifecycle work without trusting its cancellation behavior."""
        task = asyncio.ensure_future(awaitable)
        done, _pending = await asyncio.wait((task,), timeout=max(0.01, timeout))
        if not done:
            task.cancel()
            task.add_done_callback(self._consume_detached_task)
            logger.warning("gateway %s exceeded %.2fs; detached during shutdown", label, timeout)
            return False
        try:
            await task
            return True
        except asyncio.CancelledError:
            return False
        except Exception:
            logger.warning("gateway %s failed during shutdown", label, exc_info=True)
            return False

    async def _cancel_tick_task(self, timeout: float) -> None:
        task = self._tick_task
        self._tick_task = None
        if task is None or task is asyncio.current_task():
            return
        if not task.done():
            task.cancel()
        done, _pending = await asyncio.wait((task,), timeout=max(0.01, timeout))
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        else:
            task.add_done_callback(self._consume_detached_task)
            logger.warning("gateway supervision task did not cancel within %.2fs", timeout)

    async def _stop_all(self, *, timeout: Optional[float] = None) -> None:
        """Gracefully shut down all platforms: cancel tick, disconnect, persist.

        Bound the disconnect phase by ``shutdown_timeout`` so a hung adapter
        never blocks shutdown; disabled/crashed runtimes keep their state so it
        is honoured on the next start.
        """
        self._running = False
        bound = max(0.01, float(timeout if timeout is not None else self.config["shutdown_timeout"]))
        stop_delivery = getattr(self._runner, "stop_delivery_loop", None)
        if callable(stop_delivery):
            await self._await_bounded(stop_delivery(), bound, "delivery worker stop")
        await self._cancel_tick_task(bound)

        # Fence connect attempts before disconnecting, then disconnect all
        # adapters concurrently. Each disconnect receives the same hard bound,
        # so total shutdown time does not grow linearly with platform count.
        for rt in self.runtimes.values():
            rt.cancel_connect()
        if self.runtimes:
            await asyncio.gather(*(
                self._await_bounded(rt.adapter.disconnect(), bound, f"disconnect {rt.platform}")
                for rt in self.runtimes.values()
            ))
        for rt in self.runtimes.values():
            if rt.state != STATE_DISABLED:
                rt._set_state(STATE_STOPPED)
                rt._set_health(HEALTH_UNAVAILABLE)
        self._store.save(self._snapshot())
        logger.info("Gateway supervisor stopped %d platform(s)", len(self.runtimes))

    # ------------------------------------------------------------------ #
    # Message routing passthrough
    # ------------------------------------------------------------------ #
    async def handle_message(self, event):
        """Route an incoming message through the shared runner pipeline."""
        await self._runner.handle_message(event)

    def _snapshot(self) -> Dict[str, dict]:
        return {name: rt.snapshot() for name, rt in self.runtimes.items()}
