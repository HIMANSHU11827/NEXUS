"""Redesign regression tests for the NEXUS plugin system (``plugins/``).

Covers the redesigned plugin layer:
  (a) full lifecycle stages on ``PluginRecord`` (discovered → validated →
      loading → loaded → initialized → enabled → disabled → uninstalled, plus
      failed) and persistence to ``~/.nexus/plugins/state.json`` (atomic stdlib,
      never raises).
  (b) fault isolation: a crashing plugin never blocks other plugins and three
      consecutive errors auto-disable a plugin with reason ``crash_loop``.
  (c) capability allowlist: a plugin that registers a tool whose capability was
      not granted is denied at the registration boundary.
  (d) uninstall removes every registered tool / hook / CLI command.
  (e) ``pre_tool_call``-style hook block returns are surfaced as a structured
      ``{"action": "block", "reason": ...}`` decision.

Each test rebuilds the plugin tree under a fresh temp dir and rebuilds a fresh
PluginManager (after resetting the ThreadSafeSingleton) so the real ``~/.nexus``
plugin state is never touched.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from plugins.manager import HookRegistry, PluginManager, PluginStage


# ── isolation fixture ────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _fresh_plugin_manager():
    """Reset the singleton so every test builds its own PluginManager."""
    PluginManager._reset_instance()
    yield
    PluginManager._reset_instance()


# ── helpers ──────────────────────────────────────────────────────────────────
_SIMPLE_PLUGIN = (
    "def register(ctx):\n"
    "    def handler(**kw):\n"
    "        return 'ok'\n"
    "    ctx.register_tool('p_tool', {'name': 'p_tool'}, handler)\n"
)

_FULL_PLUGIN = _SIMPLE_PLUGIN + (
    "    ctx.register_hook('pre_tool_call', lambda *a, **k: 'hooked')\n"
    "    ctx.register_cli_command('pcmd', lambda: 'cmd')\n"
)

_CRASHY_TOOL_PLUGIN = (
    "def register(ctx):\n"
    "    def boom(**kw):\n"
    "        raise RuntimeError('crash')\n"
    "    ctx.register_tool('crash_tool', {'name': 'crash_tool'}, boom)\n"
)


def _write_plugin(root: Path, name: str, init_code: str, meta=None, user: bool = False) -> Path:
    base = root / (".nexus" / "plugins" if user else "plugins")
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "1.0.0", **(meta or {})}
    (plugin_dir / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "__init__.py").write_text(init_code, encoding="utf-8")
    return plugin_dir


def _make_manager(tmp_path) -> PluginManager:
    pm = PluginManager.__new__(PluginManager)
    pm._initialized = True
    pm.root = str(tmp_path)
    pm._bundled_dir = str(tmp_path / "plugins")
    pm._user_dir = str(tmp_path / ".nexus" / "plugins")
    pm._kernel = MagicMock()
    pm._kernel.tools._tools = {}
    pm._hook_registry = HookRegistry()
    pm._hook_registry.on_fault = pm._hook_fault_handler
    pm._loaded_plugins = {}
    pm._discovered = []
    pm._lock = threading.RLock()
    pm._state_path_override = str(tmp_path / ".nexus" / "plugins" / "state.json")
    pm._ensure_dirs()
    pm._ensure_records()
    pm.discover_plugins()
    return pm


def _run(coro):
    return asyncio.run(coro)


# ── lifecycle stages + persistence ───────────────────────────────────────────
class TestLifecycle:
    def test_stage_transitions_and_persistence(self, tmp_path):
        _write_plugin(tmp_path, "multi", _FULL_PLUGIN)
        pm = _make_manager(tmp_path)

        rec = pm.get_plugin_record("multi")
        assert rec is not None
        assert rec.state == PluginStage.DISCOVERED
        assert rec.state.value == "discovered"

        assert pm.load_plugin("multi") is True
        rec = pm.get_plugin_record("multi")
        assert rec.state == PluginStage.ENABLED
        stages = [h["stage"] for h in rec.history]
        # Applied in order: discovered → validated → loading → loaded →
        # initialized → enabled (history starts after discovery).
        for a, b in zip(
            ["validated", "loading", "loaded", "initialized", "enabled"],
            stages[-5:],
        ):
            assert a == b, f"expected {a}, saw {b}"
        assert "multi" in pm.loaded_plugins

        # Disable → unregisters everything and records the disabled stage.
        assert pm.disable_plugin("multi") is True
        assert pm.loaded_plugins == {}
        assert pm.get_plugin_record("multi").state == PluginStage.DISABLED
        assert pm.get_plugin_record("multi").state.value == "disabled"

        # State persisted to ~/.nexus/plugins/state.json (under tmp).
        state_path = tmp_path / ".nexus" / "plugins" / "state.json"
        assert state_path.is_file()
        with open(state_path, encoding="utf-8") as f:
            persisted = json.load(f)
        assert persisted["plugins"]["multi"]["state"] == "disabled"

        # A fresh manager restores the disabled stage from the state file.
        PluginManager._reset_instance()
        pm2 = _make_manager(tmp_path)
        assert pm2.get_plugin_record("multi").state == PluginStage.DISABLED
        # load_plugin honors the persisted disabled state (must enable first).
        assert pm2.load_plugin("multi") is False

        # enable_plugin re-enables and loads it.
        assert pm2.enable_plugin("multi") is True
        assert pm2.get_plugin_record("multi").state == PluginStage.ENABLED
        assert "multi" in pm2.loaded_plugins

    def test_failed_stage_on_load_error(self, tmp_path):
        _write_plugin(tmp_path, "bad", "def register(ctx):\n    raise RuntimeError('boom')\n")
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("bad") is False
        assert pm.get_plugin_record("bad").state == PluginStage.FAILED
        assert "bad" not in pm.loaded_plugins


# ── fault isolation + crash-loop auto-disable ────────────────────────────────
class TestFaultIsolation:
    def test_crashing_plugin_does_not_block_others(self, tmp_path):
        _write_plugin(tmp_path, "good", _FULL_PLUGIN)
        _write_plugin(tmp_path, "bad", "def register(ctx):\n    raise RuntimeError('boom')\n")
        pm = _make_manager(tmp_path)

        assert pm.load_plugin("good") is True
        # The crashing plugin fails on its own; the good plugin stays healthy.
        assert pm.load_plugin("bad") is False
        assert "good" in pm.loaded_plugins
        assert "bad" not in pm.loaded_plugins
        assert "p_tool" in pm._kernel.tools._tools
        assert pm.get_plugin_record("good").state == PluginStage.ENABLED

    def test_auto_disable_after_three_consecutive_errors(self, tmp_path):
        _write_plugin(tmp_path, "crashy", _CRASHY_TOOL_PLUGIN)
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("crashy") is True
        adapter = pm.loaded_plugins["crashy"].registered_tools["crash_tool"]

        # First two failures are counted but tolerated.
        _run(adapter.execute())
        _run(adapter.execute())
        assert pm.get_plugin_record("crashy").state == PluginStage.ENABLED
        assert pm.get_plugin_record("crashy").consecutive_errors == 2

        # Third consecutive failure auto-disables with reason crash_loop and
        # removes the plugin's tool from the live registry.
        _run(adapter.execute())
        rec = pm.get_plugin_record("crashy")
        assert rec.state == PluginStage.DISABLED
        assert rec.state.value == "disabled"
        assert rec.reason == "crash_loop"
        assert rec.consecutive_errors == 3
        assert "crashy" not in pm.loaded_plugins
        assert "crash_tool" not in pm._kernel.tools._tools

    def test_crash_loop_reason_persisted(self, tmp_path):
        _write_plugin(tmp_path, "crashy", _CRASHY_TOOL_PLUGIN)
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("crashy") is True
        adapter = pm.loaded_plugins["crashy"].registered_tools["crash_tool"]
        for _ in range(3):
            _run(adapter.execute())
        state_path = tmp_path / ".nexus" / "plugins" / "state.json"
        with open(state_path, encoding="utf-8") as f:
            persisted = json.load(f)
        assert persisted["plugins"]["crashy"]["state"] == "disabled"
        assert persisted["plugins"]["crashy"]["reason"] == "crash_loop"
        assert persisted["plugins"]["crashy"]["consecutive_errors"] == 3


# ── capability allowlist gating ──────────────────────────────────────────────
class TestCapabilityGate:
    def test_denies_ungranted_tool_registration(self, tmp_path):
        # Explicit manifest grants only ``hooks`` — tools and cli are not granted.
        _write_plugin(
            tmp_path,
            "limited",
            (
                "def register(ctx):\n"
                "    ctx.register_tool('secret_tool', {'name': 'secret_tool'}, lambda **kw: 'ok')\n"
                "    ctx.register_hook('pre_tool_call', lambda *a, **k: None)\n"
                "    ctx.register_cli_command('secret_cmd', lambda: 'x')\n"
            ),
            meta={"capabilities": ["hooks"]},
        )
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("limited") is True
        ctx = pm.loaded_plugins["limited"]

        # Tools and cli are denied; the hook is allowed.
        assert "secret_tool" not in pm._kernel.tools._tools
        assert len(pm.get_hooks("pre_tool_call")) == 1
        assert ctx.denied_registrations  # denials are observable
        kinds = {item["kind"] for item in ctx.denied_registrations}
        assert "tool" in kinds and "cli" in kinds

        rec = pm.get_plugin_record("limited")
        assert rec.capabilities == frozenset({"hooks"})

    def test_legacy_default_grants_inprocess_surface_only(self, tmp_path):
        # No capability list in the manifest → legacy default (tools/hooks/cli),
        # but external capabilities (network/files/mcp) are NOT granted.
        _write_plugin(tmp_path, "plain", _FULL_PLUGIN)
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("plain") is True
        rec = pm.get_plugin_record("plain")
        assert "tools" in rec.capabilities
        assert "hooks" in rec.capabilities
        assert "cli" in rec.capabilities
        assert "network" not in rec.capabilities
        assert "files" not in rec.capabilities
        assert "mcp" not in rec.capabilities


# ── uninstall removes registered artifacts ───────────────────────────────────
class TestUninstall:
    def test_uninstall_unregisters_tools_hooks_and_commands(self, tmp_path):
        _write_plugin(tmp_path, "victim", _FULL_PLUGIN)
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("victim") is True
        ctx = pm.loaded_plugins["victim"]
        assert "p_tool" in pm._kernel.tools._tools
        assert len(pm.get_hooks("pre_tool_call")) == 1
        assert "pcmd" in ctx.cli_commands

        assert pm.uninstall_plugin("victim") is True
        assert "p_tool" not in pm._kernel.tools._tools
        assert pm.get_hooks("pre_tool_call") == []
        assert ctx.cli_commands == {}
        assert "victim" not in pm.loaded_plugins
        assert pm.get_plugin_record("victim").state == PluginStage.UNINSTALLED
        assert pm.get_plugin_record("victim").state.value == "uninstalled"

    def test_uninstall_persists_state(self, tmp_path):
        _write_plugin(tmp_path, "victim", _FULL_PLUGIN)
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("victim") is True
        assert pm.uninstall_plugin("victim") is True
        state_path = tmp_path / ".nexus" / "plugins" / "state.json"
        with open(state_path, encoding="utf-8") as f:
            persisted = json.load(f)
        assert persisted["plugins"]["victim"]["state"] == "uninstalled"


# ── hook block-return surfacing ──────────────────────────────────────────────
class TestHookBlocking:
    def test_block_dict_surfaces_structured(self, tmp_path):
        _write_plugin(
            tmp_path,
            "guard",
            (
                "def register(ctx):\n"
                "    ctx.register_hook('pre_tool_call', lambda *a, **k: {'action': 'block', 'reason': 'denied'})\n"
            ),
        )
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("guard") is True
        results = _run(pm.trigger_hooks("pre_tool_call", [object()]))
        blocks = [r for r in results if isinstance(r, dict) and r.get("action") == "block"]
        assert len(blocks) == 1
        assert blocks[0]["reason"] == "denied"

    def test_block_true_shape_surfaces_structured(self, tmp_path):
        _write_plugin(
            tmp_path,
            "guard2",
            (
                "def register(ctx):\n"
                "    ctx.register_hook('pre_tool_call', lambda *a, **k: {'block': True, 'message': 'no way'})\n"
            ),
        )
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("guard2") is True
        results = _run(pm.trigger_hooks("pre_tool_call", [object()]))
        blocks = [r for r in results if isinstance(r, dict) and r.get("action") == "block"]
        assert len(blocks) == 1
        assert blocks[0]["reason"] == "no way"

    def test_non_block_returns_pass_through(self, tmp_path):
        _write_plugin(
            tmp_path,
            "pass",
            (
                "def register(ctx):\n"
                "    ctx.register_hook('pre_tool_call', lambda *a, **k: 'ok')\n"
            ),
        )
        pm = _make_manager(tmp_path)
        assert pm.load_plugin("pass") is True
        results = _run(pm.trigger_hooks("pre_tool_call", [object()]))
        assert "ok" in results
        # No block decisions for a non-block hook.
        assert not any(isinstance(r, dict) and r.get("action") == "block" for r in results)
