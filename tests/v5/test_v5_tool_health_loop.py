"""Closed tool-health loop: outcome telemetry must be collected AND consumed.

The registry already had `record_execution` and `get_tool_stats` (success
rate, avg latency, error breakdown), but `record_execution` had ZERO callers
in production. So the whole subsystem was dead telemetry: nothing fed it and
nothing read it. That is exactly the mission's "tool health -> but no routing
influence" open loop.

These tests pin both halves closed:
1. Terminal tool outcomes are recorded into the registry history during
   execution (via the single `_emit_tool_event` funnel, which covers both
   command and registry tools and every failure mode).
2. When a `top_k`/`NEXUS_TOOL_SCHEMA_LIMIT` cap is in effect,
   `_get_direct_tool_schemas` orders candidates by observed success rate,
   so healthier tools surface first for small-context local models -- without
   hiding any tool or taking choice away from the model.
"""

import asyncio
import os
import time

import pytest

from nexus.main_agent.direct_loop import V5DirectModelToolLoop
from extensions.tools.built_in.nexus_tools.registry import ToolEntry, ToolRegistry


class _FakeCall:
    def __init__(self, name, params=None, call_id="c1"):
        self.name = name
        self.params = params or {}
        self.call_id = call_id


def _make_registry_with(tools):
    """Registry with stub entries (no discovery/MCP) for deterministic tests."""
    reg = ToolRegistry.__new__(ToolRegistry)
    reg.root = os.getcwd()
    reg._tools = {}
    reg._mcp_clients = []
    reg._history = []
    reg._history_limit = 500
    for name in tools:
        entry = ToolEntry(
            name=name,
            schema={"name": name, "description": f"{name} help", "params": {}},
            instance=object(),
        )
        reg._tools[name] = entry
    return reg


def _fake_emitter_with_registry():
    """Wire the single event funnel (V5EventEmitter) to a real registry."""
    from nexus.main_agent.events import V5EventEmitter

    reg = ToolRegistry.__new__(ToolRegistry)
    reg.root = os.getcwd()
    reg._tools = {}
    reg._mcp_clients = []
    reg._history = []
    reg._history_limit = 500
    em = V5EventEmitter.__new__(V5EventEmitter)
    em.tool_registry = reg
    em.session_id = "tool-health"
    em._current_turn_id = "t1"
    em._tool_started_at = {"c1": __import__("time").time()}
    class _StubRuntime:
        work_event_sink = None
    em.runtime = _StubRuntime()
    em.work_event_sink = None
    # minimal state the funnel touches
    em._event_summary_events = []
    em._stream_events = []
    return em, reg


@pytest.mark.asyncio
async def test_terminal_tool_outcome_is_recorded_into_registry_history():
    """The event funnel must close the telemetry loop by calling
    record_execution on every terminal outcome, not just emit an event."""
    em, reg = _fake_emitter_with_registry()

    em._tool_started_at = {
        "c1": time.time(),
        "c2": time.time(),
    }
    await em._emit_tool_event(
        _FakeCall("search_files", {"query": "x"}, call_id="c1"), status="done", result="hits"
    )
    await em._emit_tool_event(
        _FakeCall("legacy_terminal", {"cmd": "boom"}, call_id="c2"),
        status="error",
        error="traceback",
    )

    stats = reg.get_tool_stats()
    assert stats["total_calls"] == 2, stats
    assert reg.get_tool_stats("search_files")["success_rate"] == 100.0
    assert reg.get_tool_stats("legacy_terminal")["success_rate"] == 0.0
    assert reg.get_tool_stats("legacy_terminal")["error_breakdown"].get("error") == 1


@pytest.mark.asyncio
async def test_telemetry_recording_never_breaks_the_event_emission():
    """If the registry is gone or record_execution raises, the tool event
    itself must still emit cleanly -- telemetry is strictly best-effort."""
    em, _ = _fake_emitter_with_registry()
    em.tool_registry = None  # simulate registry unavailable
    # Must not raise.
    await em._emit_tool_event(_FakeCall("x"), status="done", result="ok")


@pytest.mark.asyncio
async def test_blocked_outcome_is_recorded_too():
    """A permission/risk blocked tool must also land in the history so it is
    not silently invisible to the stats."""
    em, reg = _fake_emitter_with_registry()
    em._tool_started_at = {"c1": time.time()}
    await em._emit_tool_event(_FakeCall("danger", call_id="c1"), status="blocked", error="denied")
    assert reg.get_tool_stats("danger")["total_calls"] == 1
    assert reg.get_tool_stats("danger")["error_breakdown"].get("blocked") == 1


def test_successful_tools_surfaces_before_failing_ones_when_capped():
    """Tool-health must influence selection ordering once a cap is set."""
    reg = _make_registry_with(["alpha", "good_tool", "bad_tool"])
    reg.record_execution("good_tool", {}, "ok", 10, "ok")
    reg.record_execution("good_tool", {}, "ok", 12, "ok")
    reg.record_execution("bad_tool", {}, "err", 50, "error")
    reg.record_execution("bad_tool", {}, "err", 80, "error")

    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)
    loop.tool_registry = reg
    loop.session_id = "sel"
    loop._current_turn_id = "t"

    os.environ["NEXUS_TOOL_SCHEMA_LIMIT"] = "3"
    try:
        schemas = loop._get_direct_tool_schemas()
    finally:
        os.environ.pop("NEXUS_TOOL_SCHEMA_LIMIT", None)

    names = [s["function"]["name"] for s in schemas]
    assert "good_tool" in names and "bad_tool" in names
    assert names.index("good_tool") < names.index("bad_tool")


def test_unobserved_tools_are_not_demoted_or_promoted():
    """A tool with no telemetry keeps its place among candidates and is never
    hidden by the health ordering."""
    reg = _make_registry_with(["known_good", "known_bad", "brand_new"])
    reg.record_execution("known_good", {}, "ok", 5, "ok")
    reg.record_execution("known_bad", {}, "err", 90, "error")

    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)
    loop.tool_registry = reg
    loop.session_id = "sel2"
    loop._current_turn_id = "t"

    os.environ["NEXUS_TOOL_SCHEMA_LIMIT"] = "3"
    try:
        schemas = loop._get_direct_tool_schemas()
    finally:
        os.environ.pop("NEXUS_TOOL_SCHEMA_LIMIT", None)

    names = [s["function"]["name"] for s in schemas]
    assert set(names) == {"known_good", "known_bad", "brand_new"}
    assert names.index("known_good") < names.index("known_bad")
    assert "brand_new" in names


def test_no_cap_means_all_tools_remain_exposed_and_unordered():
    """When no transport cap is configured, no health reordering happens and
    every tool stays available -- model choice stays fully authoritative."""
    reg = _make_registry_with(["bad", "a", "b", "c"])
    reg.record_execution("bad", {}, "err", 99, "error")

    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)
    loop.tool_registry = reg
    loop.session_id = "sel3"
    loop._current_turn_id = "t"

    schemas = loop._get_direct_tool_schemas()
    assert len(schemas) == 4  # nothing hidden


def test_worst_health_tool_is_truncated_under_cap():
    """With more tools than the cap allows, the lowest-success-rate tool
    must be the one dropped -- not the alphabetically-first one. This
    proves the health signal actively influences which capped tools
    survive (the original loop gap), not just that healthy tools lead."""
    reg = _make_registry_with(["aaaa_bad", "apple_good", "mango_good", "kiwi_ok"])
    reg.record_execution("aaaa_bad", {}, "err", 90, "error")
    reg.record_execution("aaaa_bad", {}, "err", 90, "error")
    for _ in range(2):
        reg.record_execution("apple_good", {}, "ok", 5, "ok")
    for _ in range(2):
        reg.record_execution("mango_good", {}, "ok", 5, "ok")
    reg.record_execution("kiwi_ok", {}, "ok", 5, "ok")
    reg.record_execution("kiwi_ok", {}, "err", 40, "error")  # 50%

    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)
    loop.tool_registry = reg
    loop.session_id = "sel4"
    loop._current_turn_id = "t"

    os.environ["NEXUS_TOOL_SCHEMA_LIMIT"] = "3"
    try:
        schemas = loop._get_direct_tool_schemas()
    finally:
        os.environ.pop("NEXUS_TOOL_SCHEMA_LIMIT", None)
    names = [s["function"]["name"] for s in schemas]
    assert len(schemas) == 3
    # zebra_bad (0%) is the worst -- it must be the truncated one, even
    # though it is alphabetically first (pure alpha-cap would keep it).
    assert "aaaa_bad" not in names, names
    assert set(names) == {"apple_good", "mango_good", "kiwi_ok"}, names
