"""Tests for the redesigned lifecycle layer: LifecycleStage + ComponentSupervisor.

Covers:
- Legal/illegal stage transitions (no ghost states, rejections carry a reason)
- Dependency-ordered startup / reverse shutdown
- Failure isolation (one failing component never blocks the rest) + quarantine
- Restart recovery through recovering -> ready (with cooldown + readiness check)
- Stage persistence + restore across supervisor instances
- Timeout on a hung async component
"""

import asyncio
import time
import uuid

import pytest

from lifecycle import (
    ComponentSupervisor,
    LifecycleStage,
    StageTransitionError,
    get_component_supervisor,
)
from lifecycle.persistence import clear_state


def make_supervisor(**kwargs):
    """Fresh in-memory supervisor; tests opt into persistence explicitly."""
    kwargs.setdefault("persist", False)
    return ComponentSupervisor(**kwargs)


def _to_ready(sup, cid):
    """Walk a component through the legal path to READY."""
    sup.mark_stage(cid, LifecycleStage.INITIALIZING)
    sup.mark_stage(cid, LifecycleStage.READY)


class TestStageMachine:
    def test_happy_path_transitions_are_legal(self):
        sup = make_supervisor()
        sup.register("core")
        assert sup.get_stage("core") == LifecycleStage.CREATED
        assert sup.may_transition("CREATED", "INITIALIZING") is True
        sup.mark_stage("core", LifecycleStage.INITIALIZING)
        sup.mark_stage("core", LifecycleStage.READY)
        sup.mark_stage("core", LifecycleStage.RUNNING)
        sup.mark_stage("core", LifecycleStage.PAUSED)
        sup.mark_stage("core", LifecycleStage.READY)
        sup.mark_stage("core", LifecycleStage.STOPPING)
        sup.mark_stage("core", LifecycleStage.STOPPED)
        assert sup.get_stage("core") == LifecycleStage.STOPPED

    def test_illegal_transition_rejected_with_reason(self):
        sup = make_supervisor()
        sup.register("core")
        # created -> ready skips initializing, so it must be rejected.
        ok, reason = sup.try_mark_stage("core", LifecycleStage.READY)
        assert ok is False
        assert "illegal transition" in reason
        assert "CREATED" in reason
        # No ghost state: the component stays where it was.
        assert sup.get_stage("core") == LifecycleStage.CREATED
        with pytest.raises(StageTransitionError):
            sup.mark_stage("core", LifecycleStage.QUARANTINED)

    def test_unregistered_component_rejected(self):
        sup = make_supervisor()
        ok, reason = sup.try_mark_stage("ghost", LifecycleStage.READY)
        assert ok is False
        assert "not registered" in reason

    def test_stage_names_resolved_from_strings(self):
        sup = make_supervisor()
        sup.register("c")
        sup.mark_stage("c", "INITIALIZING")
        sup.mark_stage("c", "READY")
        assert sup.get_stage("c") == LifecycleStage.READY

    def test_same_stage_is_a_noop(self):
        sup = make_supervisor()
        sup.register("c")
        sup.mark_stage("c", LifecycleStage.INITIALIZING)
        assert sup.mark_stage("c", LifecycleStage.INITIALIZING) is True
        assert sup.get_component("c")["fail_count"] == 0

    def test_crash_recovery_path(self):
        # running -> recovering -> ready is a normal recovery flow.
        sup = make_supervisor()
        sup.register("w")
        _to_ready(sup, "w")
        sup.mark_stage("w", LifecycleStage.RUNNING)
        sup.mark_stage("w", LifecycleStage.RECOVERING)
        sup.mark_stage("w", LifecycleStage.READY)
        assert sup.get_stage("w") == LifecycleStage.READY

    def test_transition_reason_is_none_when_legal(self):
        sup = make_supervisor()
        assert sup.transition_reason("CREATED", "INITIALIZING") is None
        assert sup.transition_reason("CREATED", "RUNNING") is not None
        assert sup.may_transition("CREATED", "INITIALIZING") is True
        assert sup.may_transition("FAILED", "READY") is False


class TestStartupShutdownOrdering:
    async def test_startup_in_after_order_and_shutdown_reverse(self):
        sup = make_supervisor()
        order = []

        def start_a():
            order.append("start_a")

        def start_b():
            order.append("start_b")

        def stop_a():
            order.append("stop_a")

        def stop_b():
            order.append("stop_b")

        specs = [
            {"id": "a", "name": "A", "startup": start_a, "shutdown": stop_a, "after": ["b"]},
            {"id": "b", "name": "B", "startup": start_b, "shutdown": stop_b, "after": []},
        ]
        out = await sup.startup(specs)
        # b has no deps and must start first; a waits for b.
        assert order == ["start_b", "start_a"]
        assert {k: v["status"] for k, v in out.items()} == {"a": "started", "b": "started"}
        assert sup.get_stage("a") == LifecycleStage.READY
        assert sup.get_stage("b") == LifecycleStage.READY

        order.clear()
        out = await sup.shutdown(specs)
        # Shutdown is the reverse of the startup order: a stops before b.
        assert order == ["stop_a", "stop_b"]
        assert sup.get_stage("a") == LifecycleStage.STOPPED
        assert sup.get_stage("b") == LifecycleStage.STOPPED

    async def test_object_and_registered_id_specs(self):
        sup = make_supervisor()

        class Comp:
            def __init__(self, cid, after=()):
                self.id = cid
                self.after = list(after)
                self.started = 0

            async def startup(self):
                self.started += 1

        a = Comp("a", after=["b"])
        b = Comp("b")
        out = await sup.startup([a, b])
        assert {k: v["status"] for k, v in out.items()} == {"a": "started", "b": "started"}
        assert a.started == 1 and b.started == 1
        assert sup.get_stage("a") == LifecycleStage.READY

        # A bare registered id starts with transitions only (no callable).
        sup2 = make_supervisor()
        sup2.register("x", "X", after=[])
        out = await sup2.startup(["x"])
        assert out["x"]["status"] == "started"
        assert sup2.get_stage("x") == LifecycleStage.READY
        # Re-starting an already-healthy component is skipped.
        out = await sup2.startup(["x"])
        assert out["x"]["status"] == "skipped"

    async def test_dependency_cycle_marked_failed_not_blocked(self):
        sup = make_supervisor()
        specs = [
            {"id": "a", "name": "A", "startup": (lambda: None), "after": ["b"]},
            {"id": "b", "name": "B", "startup": (lambda: None), "after": ["a"]},
            {"id": "c", "name": "C", "startup": (lambda: None), "after": []},
        ]
        out = await sup.startup(specs)
        assert out["a"]["status"] == "cyclic"
        assert out["b"]["status"] == "cyclic"
        assert out["c"]["status"] == "started"
        assert sup.get_stage("a") == LifecycleStage.FAILED
        assert sup.get_stage("c") == LifecycleStage.READY


class TestFailureIsolationAndQuarantine:
    async def test_failing_component_does_not_block_others(self):
        sup = make_supervisor()
        started = []

        def good():
            started.append("good")
            return "ok"

        def bad():
            started.append("bad")
            raise RuntimeError("boom")

        specs = [
            {"id": "bad", "name": "Bad", "startup": bad, "after": []},
            {"id": "good", "name": "Good", "startup": good, "after": ["bad"]},
        ]
        out = await sup.startup(specs)
        assert out["bad"]["status"] == "failed"
        assert out["good"]["status"] == "started"
        assert sup.get_stage("bad") == LifecycleStage.FAILED
        assert sup.get_stage("good") == LifecycleStage.READY
        assert started.count("good") == 1

    async def test_quarantines_after_three_start_failures(self):
        sup = make_supervisor()

        def bad():
            raise RuntimeError("boom")

        def good():
            return "ok"

        specs = [
            {"id": "bad", "name": "Bad", "startup": bad, "after": []},
            {"id": "good", "name": "Good", "startup": good, "after": []},
        ]
        await sup.startup(specs)
        assert sup.get_stage("bad") == LifecycleStage.FAILED
        assert sup.get_component("bad")["fail_count"] == 1
        await sup.startup(specs)
        assert sup.get_stage("bad") == LifecycleStage.FAILED
        assert sup.get_component("bad")["fail_count"] == 2
        out = await sup.startup(specs)
        assert out["bad"]["status"] == "quarantined"
        assert sup.get_stage("bad") == LifecycleStage.QUARANTINED
        assert sup.get_component("bad")["fail_count"] == 3
        # The healthy component stays ready and is not re-run.
        assert sup.get_stage("good") == LifecycleStage.READY


class TestRestartRecovery:
    async def test_restart_recovers_after_cooldown(self):
        sup = make_supervisor()
        sup.register("w", "Worker", cooldown=0.1)
        _to_ready(sup, "w")
        sup.mark_stage("w", LifecycleStage.RUNNING)
        sup.mark_stage("w", LifecycleStage.FAILED)

        start = time.perf_counter()
        ok, detail = await sup.restart("w", check=lambda: True)
        elapsed = time.perf_counter() - start
        assert ok is True
        assert sup.get_stage("w") == LifecycleStage.READY
        assert sup.get_component("w")["fail_count"] == 0
        assert sup.get_component("w")["restart_count"] == 1
        # The readiness check only runs after the cooldown elapses.
        assert elapsed >= 0.09

    async def test_restart_immediate_without_check(self):
        sup = make_supervisor()
        sup.register("w", "Worker", cooldown=5.0)  # large cooldown: no check -> no sleep
        _to_ready(sup, "w")
        sup.mark_stage("w", LifecycleStage.FAILED)
        start = time.perf_counter()
        ok, _detail = await sup.restart("w")
        assert ok is True
        assert time.perf_counter() - start < 1.0
        assert sup.get_stage("w") == LifecycleStage.READY

    async def test_restart_check_failure_keeps_component_failed(self):
        sup = make_supervisor()
        sup.register("w", "Worker", cooldown=0.01)
        _to_ready(sup, "w")
        sup.mark_stage("w", LifecycleStage.FAILED)
        ok, detail = await sup.restart("w", check=lambda: False)
        assert ok is False
        assert "check" in detail
        assert sup.get_stage("w") == LifecycleStage.FAILED
        # The component did not recover; its restart counter is untouched.
        assert sup.get_component("w")["restart_count"] == 0

    async def test_restart_of_quarantined_component(self):
        sup = make_supervisor()
        sup.register("q", "Quarantined", cooldown=0.01)
        _to_ready(sup, "q")
        sup.mark_stage("q", LifecycleStage.FAILED)
        sup.mark_stage("q", LifecycleStage.QUARANTINED)
        ok, _detail = await sup.restart("q")
        assert ok is True
        assert sup.get_stage("q") == LifecycleStage.READY
        assert sup.get_component("q")["fail_count"] == 0

    async def test_restart_rejects_non_recoverable_stages(self):
        sup = make_supervisor()
        sup.register("ok")
        _to_ready(sup, "ok")
        ok, detail = await sup.restart("ok")
        assert ok is False
        assert "cannot restart" in detail
        assert sup.get_stage("ok") == LifecycleStage.READY


class TestTimeout:
    async def test_timeout_on_hung_async_component(self):
        sup = make_supervisor()

        async def hang():
            await asyncio.sleep(10)

        def fast():
            return "ok"

        specs = [
            {"id": "slow", "name": "Slow", "startup": hang, "timeout": 0.1, "after": []},
            {"id": "fast", "name": "Fast", "startup": fast, "timeout": 0.1, "after": ["slow"]},
        ]
        out = await sup.startup(specs)
        assert out["slow"]["status"] == "failed"
        assert "timed out" in out["slow"]["detail"]
        # The hung component did not block the rest of the startup batch.
        assert out["fast"]["status"] == "started"
        assert sup.get_stage("slow") == LifecycleStage.FAILED
        assert sup.get_stage("fast") == LifecycleStage.READY


class TestPersistence:
    def test_transitions_persisted_and_restored_across_instances(self):
        key = f"test_supervisor_{uuid.uuid4().hex}"
        try:
            sup = ComponentSupervisor(persist_key=key)
            sup.register("a", "Alpha", after=["b"])
            sup.register("b", "Beta", after=[])
            _to_ready(sup, "a")
            _to_ready(sup, "b")
            sup.mark_stage("b", LifecycleStage.RUNNING)

            # A brand-new supervisor instance must pick up the last-known stages.
            sup2 = ComponentSupervisor(persist_key=key)
            assert sup2.get_stage("a") == LifecycleStage.READY
            assert sup2.get_stage("b") == LifecycleStage.RUNNING
            comp = sup2.get_component("a")
            assert comp["name"] == "Alpha"
            assert comp["after"] == ["b"]
            # Re-registering after restore keeps the restored stage.
            sup2.register("a", "Alpha", after=["b"])
            assert sup2.get_stage("a") == LifecycleStage.READY
        finally:
            clear_state(key)

    def test_disabled_persistence_is_not_shared(self):
        key = f"test_supervisor_disabled_{uuid.uuid4().hex}"
        from lifecycle.persistence import load_state
        try:
            sup = ComponentSupervisor(persist_key=key, persist=False)
            sup.register("a", "Alpha")
            _to_ready(sup, "a")
            assert load_state(key) is None
        finally:
            clear_state(key)


class TestModuleAPI:
    def test_module_level_get_component_supervisor(self):
        sup = get_component_supervisor()
        assert isinstance(sup, ComponentSupervisor)
        # Export cleanup: reset the singleton so no state leaks into other tests.
        get_component_supervisor(reset=True)
