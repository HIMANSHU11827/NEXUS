__version__ = "1.0.0"

import asyncio
import json
import os
import tempfile

import pytest

from tools.nexus_tools.base_tool import ToolResult
from plugins.manager import (
    HookRegistry,
    PluginContext,
    PluginManager,
    PluginToolAdapter,
)


class TestHookRegistry:
    @pytest.fixture
    def registry(self):
        return HookRegistry()

    def test_register_and_trigger(self, registry):
        results = []

        async def cb(x):
            results.append(f"cb:{x}")

        registry.register("pre_tool_call", cb)
        assert len(registry.get_hooks("pre_tool_call")) == 1

        asyncio.run(registry.trigger("pre_tool_call", "test"))
        assert "cb:test" in results

    def test_register_unknown_event(self, registry):
        registry.register("unknown_event", lambda: None)
        assert registry.get_hooks("unknown_event") == []

    def test_unregister_removes_one_callback(self, registry):
        def cb():
            return "ok"

        registry.register("pre_tool_call", cb)
        assert registry.unregister("pre_tool_call", cb) is True
        assert registry.unregister("pre_tool_call", cb) is False
        assert registry.get_hooks("pre_tool_call") == []

    def test_sync_callback(self, registry):
        results = []

        def cb(msg):
            results.append(f"sync:{msg}")

        registry.register("pre_llm_call", cb)
        asyncio.run(registry.trigger("pre_llm_call", "hello"))
        assert "sync:hello" in results

    def test_callback_error_does_not_break(self, registry):
        def cb():
            raise ValueError("oops")

        registry.register("post_tool_call", cb)
        registry.register("post_tool_call", lambda: "ok")

        results = asyncio.run(registry.trigger("post_tool_call"))
        assert results == ["ok"]

    def test_all_events_registered(self, registry):
        expected = {
            "pre_tool_call", "post_tool_call",
            "pre_llm_call", "post_llm_call",
            "on_session_start", "on_session_end",
        }
        assert set(registry._callbacks.keys()) == expected


class TestPluginToolAdapter:
    @pytest.fixture
    def sync_handler(self):
        def handler(text):
            return f"processed:{text}"
        return handler

    @pytest.fixture
    def async_handler(self):
        async def handler(text):
            return f"async:{text}"
        return handler

    def test_sync_execute(self, sync_handler):
        adapter = PluginToolAdapter("test_sync", sync_handler)
        result = asyncio.run(adapter.execute(text="hello"))
        assert result.success
        assert "processed:hello" in result.output

    def test_async_execute(self, async_handler):
        adapter = PluginToolAdapter("test_async", async_handler)
        result = asyncio.run(adapter.execute(text="world"))
        assert result.success
        assert "async:world" in result.output

    def test_handler_error_returns_failure(self):
        def failing():
            raise RuntimeError("fail")

        PluginToolAdapter("fail", lambda **kw: (_ for _ in ()).throw(RuntimeError("fail")))
        # Actually use a real failing handler
        async def bad(**kw):
            raise ValueError("bad")
        adapter2 = PluginToolAdapter("fail2", bad)
        result = asyncio.run(adapter2.execute())
        assert not result.success
        assert "bad" in result.error

    def test_none_result_is_not_reported_as_success(self):
        adapter = PluginToolAdapter("empty", lambda: None)

        result = asyncio.run(adapter.execute())

        assert not result.success
        assert "no result" in result.error.lower()

    @pytest.mark.parametrize("failure", [
        {"success": False, "error": "declared failure"},
        {"status": "error", "error": "status failure"},
        {"isError": True, "content": [{"type": "text", "text": "mcp failure"}]},
    ])
    def test_mapping_failures_are_canonicalized(self, failure):
        adapter = PluginToolAdapter("mapping-failure", lambda: failure)

        result = asyncio.run(adapter.execute())

        assert not result.success
        assert result.status == "error"
        assert result.error

    def test_stream_mapping_failure_remains_structured(self):
        async def failure_stream():
            yield "partial output"
            yield {"isError": True, "content": "stream declared failure"}

        async def collect():
            adapter = PluginToolAdapter("mapping-stream", failure_stream)
            return [item async for item in adapter.stream_execute()]

        items = asyncio.run(collect())
        assert items[0] == "partial output"
        assert isinstance(items[1], ToolResult)
        assert not items[1].success
        assert items[1].status == "error"
        assert "stream declared failure" in items[1].error

    def test_stream_failure_remains_structured(self):
        async def bad_stream():
            raise RuntimeError("stream exploded")
            yield "unreachable"

        async def collect():
            return [item async for item in PluginToolAdapter("bad-stream", bad_stream).stream_execute()]

        items = asyncio.run(collect())
        assert len(items) == 1
        assert isinstance(items[0], ToolResult)
        assert not items[0].success
        assert "stream exploded" in items[0].error


class TestPluginContext:
    @pytest.fixture
    def ctx(self):
        from unittest.mock import MagicMock
        kernel = MagicMock()
        kernel.tools._tools = {}
        hr = HookRegistry()
        return PluginContext("test_plugin", "/tmp/plugin", kernel, hr)

    def test_get_config_none(self, ctx):
        assert ctx.get_config("missing") is None

    def test_register_cli_command(self, ctx):
        def handler():
            pass
        ctx.register_cli_command("mycmd", handler)
        assert "mycmd" in ctx.cli_commands

    def test_register_hook(self, ctx):
        def cb():
            pass
        ctx.register_hook("pre_tool_call", cb)
        assert len(ctx._hooks.get_hooks("pre_tool_call")) == 1
        assert ctx.registered_hooks == [("pre_tool_call", cb)]

    def test_register_tool_tracks_owned_adapter(self, ctx):
        def handler(**_kwargs):
            return "ok"

        ctx.register_tool("plugin_demo", {"name": "plugin_demo"}, handler)

        assert "plugin_demo" in ctx.registered_tools
        assert ctx._kernel.tools._tools["plugin_demo"].instance is ctx.registered_tools["plugin_demo"]


class TestPluginManager:
    def test_singleton_initialization(self):
        pm1 = PluginManager()
        pm2 = PluginManager()
        assert pm1 is pm2

    def test_discover_empty(self):
        with tempfile.TemporaryDirectory() as td:
            pm = PluginManager.__new__(PluginManager)
            pm._initialized = True
            pm.root = td
            pm._bundled_dir = os.path.join(td, "plugins")
            pm._user_dir = os.path.join(td, ".nexus", "plugins")
            pm._hook_registry = HookRegistry()
            pm._loaded_plugins = {}
            pm._lock = __import__("threading").RLock()
            pm._ensure_dirs()
            pm.discover_plugins()
            assert pm.list_plugins() == []

    def test_unload_nonexistent(self):
        pm = PluginManager()
        assert not pm.unload_plugin("nonexistent")

    def test_user_plugin_load_requires_explicit_opt_in(self, tmp_path, monkeypatch):
        user_root = tmp_path / ".nexus" / "plugins"
        plugin_dir = user_root / "sample"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "sample.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        (plugin_dir / "__init__.py").write_text("def register(ctx):\n    raise AssertionError('executed')\n", encoding="utf-8")

        pm = PluginManager.__new__(PluginManager)
        pm._initialized = True
        pm.root = str(tmp_path)
        pm._bundled_dir = str(tmp_path / "plugins")
        pm._user_dir = str(user_root)
        pm._hook_registry = HookRegistry()
        pm._loaded_plugins = {}
        pm._discovered = []
        pm._lock = __import__("threading").RLock()
        pm._ensure_dirs()

        monkeypatch.delenv("NEXUS_ALLOW_USER_PLUGIN_LOAD", raising=False)

        assert pm.load_plugin("sample") is False
        assert pm.loaded_plugins == {}

    def test_bundled_plugin_loads_without_user_plugin_opt_in(self, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "plugins" / "sample"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "sample.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        (plugin_dir / "__init__.py").write_text("def register(ctx):\n    ctx.register_cli_command('ok', lambda: 'ok')\n", encoding="utf-8")

        pm = PluginManager.__new__(PluginManager)
        pm._initialized = True
        pm.root = str(tmp_path)
        pm._bundled_dir = str(tmp_path / "plugins")
        pm._user_dir = str(tmp_path / ".nexus" / "plugins")
        pm._hook_registry = HookRegistry()
        pm._loaded_plugins = {}
        pm._discovered = []
        pm._lock = __import__("threading").RLock()
        pm._ensure_dirs()

        monkeypatch.delenv("NEXUS_ALLOW_USER_PLUGIN_LOAD", raising=False)

        assert pm.load_plugin("sample") is True
        assert "sample" in pm.loaded_plugins

    def test_inactive_plugin_metadata_is_not_loaded(self, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "plugins" / "sample"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "sample.json").write_text(
            json.dumps({"name": "sample", "active": False}),
            encoding="utf-8",
        )
        (plugin_dir / "__init__.py").write_text("def register(ctx):\n    raise AssertionError('executed')\n", encoding="utf-8")

        pm = PluginManager.__new__(PluginManager)
        pm._initialized = True
        pm.root = str(tmp_path)
        pm._bundled_dir = str(tmp_path / "plugins")
        pm._user_dir = str(tmp_path / ".nexus" / "plugins")
        pm._hook_registry = HookRegistry()
        pm._loaded_plugins = {}
        pm._discovered = []
        pm._lock = __import__("threading").RLock()
        pm._ensure_dirs()
        pm.discover_plugins()

        monkeypatch.delenv("NEXUS_ALLOW_USER_PLUGIN_LOAD", raising=False)

        assert pm.load_plugin("sample") is False
        listed = pm.list_plugins()
        assert listed == [{
            "name": "sample",
            "version": "0.0.0",
            "description": "",
            "source": "bundled",
            "active": False,
            "loaded": False,
        }]
        assert pm.loaded_plugins == {}

    def test_unload_plugin_unregisters_owned_tools_and_hooks(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        plugin_dir = tmp_path / "plugins" / "sample"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "sample.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        (plugin_dir / "__init__.py").write_text(
            "def register(ctx):\n"
            "    ctx.register_tool('sample_tool', {'name': 'sample_tool'}, lambda **kwargs: 'ok')\n"
            "    ctx.register_hook('pre_tool_call', lambda *args, **kwargs: 'hooked')\n",
            encoding="utf-8",
        )

        pm = PluginManager.__new__(PluginManager)
        pm._initialized = True
        pm.root = str(tmp_path)
        pm._bundled_dir = str(tmp_path / "plugins")
        pm._user_dir = str(tmp_path / ".nexus" / "plugins")
        pm._kernel = MagicMock()
        pm._kernel.tools._tools = {}
        pm._hook_registry = HookRegistry()
        pm._loaded_plugins = {}
        pm._discovered = []
        pm._lock = __import__("threading").RLock()
        pm._ensure_dirs()

        monkeypatch.delenv("NEXUS_ALLOW_USER_PLUGIN_LOAD", raising=False)

        assert pm.load_plugin("sample") is True
        assert "sample_tool" in pm._kernel.tools._tools
        assert len(pm.get_hooks("pre_tool_call")) == 1

        assert pm.unload_plugin("sample") is True
        assert "sample_tool" not in pm._kernel.tools._tools
        assert pm.get_hooks("pre_tool_call") == []
        assert pm.loaded_plugins == {}
