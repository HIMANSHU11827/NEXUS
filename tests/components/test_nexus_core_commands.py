"""Tests for the new authoritative Core + Central Command systems.

These validate the foundation built during Phase 1-2: Nexus Core (kernel,
state machine, capability/dependency graphs, service manager), the central
Command Bus (one handler per command, aliases, middleware, permission
enforcement), registries, events, lifecycle, and configuration precedence.
"""

import asyncio
import tempfile

import pytest

from nexus.commands import (
    CommandBus,
    CommandContext,
    CommandHandler,
    CommandRequest,
    CommandResult,
)
from nexus.commands.core.command import CommandStatus
from nexus.commands.middleware.permissions import PermissionMiddleware
from nexus.core import Nexus, SystemContext
from nexus.core.dependency_graph import DependencyGraph, DependencyNode
from nexus.core.errors import LifecycleError, StartupError
from nexus.core.state_machine import StateMachine
from nexus.events import Event, EventBus
from nexus.lifecycle import LifecycleManager, LifecycleState
from nexus.registries import ToolRegistry_, build_default_registries
from nexus.configure import ConfigureManager


# ---- Core: state machine ----------------------------------------------------
def test_state_machine_legal_and_illegal():
    fsm = StateMachine("a")
    fsm.add_transition("a", "b")
    fsm.add_transition("b", "c")
    assert fsm.can_transition("a") is True  # wildcard not set
    fsm.transition("b")
    assert fsm.state == "b"
    with pytest.raises(LifecycleError):
        fsm.transition("a")  # b -> a illegal


def test_dependency_graph_cycle_detection():
    g = DependencyGraph()
    g.add(DependencyNode("a", dependencies={"b"}))
    g.add(DependencyNode("b", dependencies={"a"}))
    with pytest.raises(Exception):
        g.resolve_order()


def test_capability_graph_replacement():
    from nexus.core.capability_graph import CapabilityGraph
    cg = CapabilityGraph()
    cg.add_provider("openai", "chat.completions")
    cg.add_provider("anthropic", "chat.completions")
    assert cg.replacement_for("chat.completions", exclude="openai") == "anthropic"


# ---- Core: kernel boot/shutdown ---------------------------------------------
@pytest.mark.asyncio
async def test_kernel_boot_advances_state_and_stops():
    nx = Nexus(SystemContext(env="test"))

    async def noop():
        pass

    nx.kernel.startup.add(1, "load_config", noop)
    await nx.kernel.boot()
    assert nx.state.value == "running"
    await nx.stop()
    assert nx.state.value == "stopped"


@pytest.mark.asyncio
async def test_kernel_startup_failure_is_fatal():
    nx = Nexus(SystemContext(env="test"))

    async def boom():
        raise RuntimeError("nope")

    nx.kernel.startup.add(1, "fail_step", boom, cls=__import__(
        "nexus.core.startup_sequence", fromlist=["StepClass"]).StepClass.FATAL)
    with pytest.raises(StartupError):
        await nx.kernel.boot()


# ---- Command bus ------------------------------------------------------------
class _TaskListHandler(CommandHandler):
    command = "task.list"
    required_permissions = ["tasks:read"]

    async def handle(self, req):
        return CommandResult.ok(["t1", "t2"])


class _GoalCreateHandler(CommandHandler):
    command = "goal.create"

    async def handle(self, req):
        return CommandResult.ok({"id": "g1"})


@pytest.mark.asyncio
async def test_bus_one_handler_alias_and_unknown():
    bus = CommandBus()
    bus.register(_TaskListHandler())
    bus.register(_GoalCreateHandler())
    bus.alias("task ls", "task.list")

    r = await bus.execute(CommandRequest("task ls"))
    assert r.status is CommandStatus.SUCCESS and r.data == ["t1", "t2"]

    r = await bus.execute(CommandRequest("goal.create", args=["ship"]))
    assert r.status is CommandStatus.SUCCESS

    r = await bus.execute(CommandRequest("nope.x"))
    assert r.status is CommandStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_bus_permission_enforcement():
    bus = CommandBus()
    bus.register(_TaskListHandler())
    bus.middleware.add(PermissionMiddleware())

    r = await bus.execute(CommandRequest("task.list", context=CommandContext(source="api")))
    assert r.status is CommandStatus.REJECTED

    r = await bus.execute(CommandRequest("task.list", context=CommandContext(permissions=["tasks:read"])))
    assert r.status is CommandStatus.SUCCESS

    r = await bus.execute(CommandRequest("task.list", context=CommandContext(permissions=["*"])))
    assert r.status is CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_bus_emits_lifecycle_events():
    bus = CommandBus()
    bus.register(_GoalCreateHandler())
    kinds = []
    bus.on_event(lambda e: kinds.append(e.kind))
    await bus.execute(CommandRequest("goal.create"))
    assert "command.received" in kinds and "command.success" in kinds


# ---- Registries -------------------------------------------------------------
def test_registry_enable_disable_is_single_source():
    reg = ToolRegistry_()
    reg.register("fs", type("T", (), {"name": "fs"})(), enabled=True)
    reg.disable("fs")
    assert reg.enabled_ids == []
    reg.enable("fs")
    assert reg.enabled_ids == ["fs"]
    assert len(build_default_registries(state_dir=tempfile.mkdtemp())) == 15


# ---- Events -----------------------------------------------------------------
def test_event_bus_pubsub():
    bus = EventBus()
    seen = []
    bus.subscribe("task.created", lambda e: seen.append(e.name))
    bus.publish(Event("task", "task.created", {"id": 1}))
    assert seen == ["task.created"]
    assert len(bus.history()) == 1


# ---- Lifecycle --------------------------------------------------------------
def test_lifecycle_forward_and_backward_guards():
    lm = LifecycleManager()
    lm.track("gateway.tg")
    for st in (LifecycleState.VALIDATED, LifecycleState.REGISTERED,
               LifecycleState.ENABLED, LifecycleState.RUNNING):
        lm.transition("gateway.tg", st)
    assert lm.is_healthy("gateway.tg")
    with pytest.raises(ValueError):
        lm.transition("gateway.tg", LifecycleState.VALIDATED)  # backward illegal
    lm.mark_failed("gateway.tg", "boom")
    assert lm.get("gateway.tg").state is LifecycleState.FAILED


# ---- Configure --------------------------------------------------------------
def test_configure_precedence(monkeypatch):
    monkeypatch.setenv("NEXUS_LOG_LEVEL", "debug")
    cm = ConfigureManager(defaults={"log": {"level": "info"}},
                           overrides={"log": {"level": "warn"}})
    assert cm.get("log.level") == "debug"  # env beats overrides
    cm.set_runtime("log.level", "trace")
    assert cm.get("log.level") == "trace"
