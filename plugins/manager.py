"""Plugin Runtime Loader for NEXUS AI — discovers, loads, and activates plugins."""

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from plugins.trust import is_bundled_plugin_dir, is_user_plugin_load_allowed
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.registry import ToolEntry
from utils.singleton import ThreadSafeSingleton

logger = logging.getLogger(__name__)


class PluginToolAdapter(BaseTool):
    """Adapts a plugin tool handler into a BaseTool for the ToolRegistry."""

    def __init__(self, name: str, handler: Callable, root_dir: Optional[str] = None) -> None:
        super().__init__(root_dir)
        self.name = name
        self._handler = handler

    async def execute(self, **kwargs) -> ToolResult:
        try:
            if inspect.iscoroutinefunction(self._handler):
                result = await self._handler(**kwargs)
            else:
                result = await asyncio.to_thread(self._handler, **kwargs)
            return ToolResult(success=True, output=str(result) if result is not None else "")
        except Exception as e:
            logger.warning(f"Plugin tool '{self.name}' error: {e}")
            return ToolResult(success=False, error=str(e))

    async def stream_execute(self, **kwargs):
        """Stream generator-based plugin output; adapt ordinary handlers safely."""
        if inspect.isasyncgenfunction(self._handler):
            async for chunk in self._handler(**kwargs):
                yield str(chunk)
            return
        if inspect.isgeneratorfunction(self._handler):
            iterator = self._handler(**kwargs)
            sentinel = object()
            while True:
                chunk = await asyncio.to_thread(next, iterator, sentinel)
                if chunk is sentinel:
                    break
                yield str(chunk)
            return
        result = await self.execute(**kwargs)
        if result.output:
            yield result.output
        if result.error:
            yield result.error


class HookRegistry:
    """Stores and invokes plugin lifecycle hook callbacks."""

    PLUGIN_EVENTS = (
        "pre_tool_call",
        "post_tool_call",
        "pre_llm_call",
        "post_llm_call",
        "on_session_start",
        "on_session_end",
    )

    def __init__(self) -> None:
        self._callbacks: Dict[str, List[Callable]] = {e: [] for e in self.PLUGIN_EVENTS}
        self._lock = threading.RLock()

    def register(self, event: str, cb: Callable) -> None:
        if event not in self._callbacks:
            logger.warning(f"Unknown hook event: {event}. Valid: {self.PLUGIN_EVENTS}")
            return
        with self._lock:
            self._callbacks[event].append(cb)

    def unregister(self, event: str, cb: Callable) -> bool:
        if event not in self._callbacks:
            return False
        with self._lock:
            callbacks = self._callbacks[event]
            try:
                callbacks.remove(cb)
                return True
            except ValueError:
                return False

    def get_hooks(self, event: str) -> List[Callable]:
        return list(self._callbacks.get(event, []))

    async def trigger(self, event: str, *args, **kwargs) -> List[Any]:
        results: List[Any] = []
        cbs = list(self._callbacks.get(event, []))
        for cb in cbs:
            try:
                if inspect.iscoroutinefunction(cb):
                    results.append(await cb(*args, **kwargs))
                else:
                    results.append(await asyncio.to_thread(cb, *args, **kwargs))
            except Exception as e:
                logger.warning(f"Plugin hook '{event}' callback error: {e}")
        return results


class PluginContext:
    """Context passed to a plugin's register() function for integration."""

    def __init__(self, plugin_name: str, plugin_dir: str, kernel, hook_registry: HookRegistry) -> None:
        self._name = plugin_name
        self._dir = plugin_dir
        self._kernel = kernel
        self._hooks = hook_registry
        self._cli_commands: Dict[str, Callable] = {}
        self._registered_tools: Dict[str, PluginToolAdapter] = {}
        self._registered_hooks: List[tuple[str, Callable]] = []

    def register_tool(self, name: str, schema: dict, handler: Callable) -> None:
        adapter = PluginToolAdapter(name, handler, root_dir=self._dir)
        entry = ToolEntry(name=name, schema=schema, instance=adapter)
        self._kernel.tools._tools[name] = entry
        self._registered_tools[name] = adapter
        logger.info(f"[PLUGIN:{self._name}] Registered tool: {name}")

    def register_hook(self, event: str, callback: Callable) -> None:
        before = len(self._hooks.get_hooks(event))
        self._hooks.register(event, callback)
        after = len(self._hooks.get_hooks(event))
        if after > before:
            self._registered_hooks.append((event, callback))
        logger.info(f"[PLUGIN:{self._name}] Registered hook: {event}")

    def register_cli_command(self, name: str, handler: Callable) -> None:
        self._cli_commands[name] = handler
        logger.info(f"[PLUGIN:{self._name}] Registered CLI command: {name}")

    def get_config(self, key: str) -> Any:
        meta_path = os.path.join(self._dir, f"{self._name}.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return meta.get("config", {}).get(key)
        except Exception as e:
            logger.warning(f"[PLUGIN:{self._name}] Failed to read config key '{key}': {e}")
            return None

    @property
    def cli_commands(self) -> Dict[str, Callable]:
        return dict(self._cli_commands)

    @property
    def registered_tools(self) -> Dict[str, PluginToolAdapter]:
        return dict(self._registered_tools)

    @property
    def registered_hooks(self) -> List[tuple[str, Callable]]:
        return list(self._registered_hooks)


class PluginManager(ThreadSafeSingleton):
    """Discovers, loads, and activates plugins from bundled and user directories."""

    def __init__(self, root_dir: Optional[str] = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        from kernel import get_nexus_kernel
        self._kernel = get_nexus_kernel(root_dir=root_dir) if root_dir else None
        self.root = root_dir or (self._kernel.root if self._kernel else os.getcwd())

        self._bundled_dir = os.path.join(self.root, "plugins")
        self._user_dir = os.path.join(os.path.expanduser("~"), ".nexus", "plugins")

        self._hook_registry = HookRegistry()
        self._loaded_plugins: Dict[str, PluginContext] = {}
        self._discovered: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

        self._ensure_dirs()
        self.discover_plugins()

    def _ensure_dirs(self) -> None:
        os.makedirs(self._bundled_dir, exist_ok=True)
        os.makedirs(self._user_dir, exist_ok=True)

    def discover_plugins(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._discovered = []
            for source_dir in (self._bundled_dir, self._user_dir):
                if not os.path.isdir(source_dir):
                    continue
                for name in os.listdir(source_dir):
                    plugin_dir = os.path.join(source_dir, name)
                    if not os.path.isdir(plugin_dir):
                        continue
                    meta = self._read_meta(plugin_dir, name)
                    if meta:
                        meta["source"] = "bundled" if source_dir == self._bundled_dir else "user"
                        self._discovered.append(meta)
            return list(self._discovered)

    def _read_meta(self, plugin_dir: str, name: str) -> Optional[Dict[str, Any]]:
        meta_path = os.path.join(plugin_dir, f"{name}.json")
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta: Dict[str, Any] = json.load(f)
            meta.setdefault("name", name)
            meta.setdefault("version", "0.0.0")
            meta.setdefault("description", "")
            meta["_dir"] = plugin_dir
            return meta
        except Exception as e:
            logger.warning(f"Failed to read plugin metadata '{name}': {e}")
            return None

    def load_plugin(self, name: str) -> bool:
        with self._lock:
            if name in self._loaded_plugins:
                return True

            plugin_dir = self._find_plugin_dir(name)
            if not plugin_dir:
                logger.warning(f"Plugin '{name}' not found in any source directory")
                return False

            meta = self._read_meta(plugin_dir, name)
            if meta and meta.get("active") is False:
                logger.warning(f"Plugin '{name}' is disabled by metadata")
                return False

            init_path = os.path.join(plugin_dir, "__init__.py")
            if not os.path.isfile(init_path):
                logger.warning(f"Plugin '{name}' has no __init__.py")
                return False

            if not is_bundled_plugin_dir(plugin_dir, self._bundled_dir) and not is_user_plugin_load_allowed():
                logger.warning(
                    "Refusing to load user plugin '%s': plugin source is executable code. "
                    "Set NEXUS_ALLOW_USER_PLUGIN_LOAD=1 only after reviewing it.",
                    name,
                )
                return False

            try:
                ctx = PluginContext(name, plugin_dir, self._kernel, self._hook_registry)
                spec = importlib.util.spec_from_file_location(f"nexus_plugin_{name}", init_path)
                if spec is None or spec.loader is None:
                    return False
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "register"):
                    mod.register(ctx)
                else:
                    logger.warning(f"Plugin '{name}' has no register() function")
                    return False
                self._loaded_plugins[name] = ctx
                logger.info(f"[PLUGIN] Loaded: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to load plugin '{name}': {e}")
                return False

    def _find_plugin_dir(self, name: str) -> Optional[str]:
        for source_dir in (self._bundled_dir, self._user_dir):
            plugin_dir = os.path.join(source_dir, name)
            if os.path.isdir(plugin_dir):
                meta_path = os.path.join(plugin_dir, f"{name}.json")
                if os.path.isfile(meta_path):
                    return plugin_dir
        return None

    def unload_plugin(self, name: str) -> bool:
        with self._lock:
            ctx = self._loaded_plugins.get(name)
            if ctx is None:
                return False
            tools = getattr(getattr(self._kernel, "tools", None), "_tools", {}) if self._kernel else {}
            for tool_name, adapter in ctx.registered_tools.items():
                entry = tools.get(tool_name) if isinstance(tools, dict) else None
                if entry is not None and getattr(entry, "instance", None) is adapter:
                    del tools[tool_name]
                    logger.info(f"[PLUGIN:{name}] Unregistered tool: {tool_name}")
            for event, callback in ctx.registered_hooks:
                if self._hook_registry.unregister(event, callback):
                    logger.info(f"[PLUGIN:{name}] Unregistered hook: {event}")
            del self._loaded_plugins[name]
            logger.info(f"[PLUGIN] Unloaded: {name}")
            return True

    def list_plugins(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for meta in self._discovered:
            name = meta.get("name", "")
            result.append({
                "name": name,
                "version": meta.get("version", "0.0.0"),
                "description": meta.get("description", ""),
                "source": meta.get("source", ""),
                "active": meta.get("active", True) is not False,
                "loaded": name in self._loaded_plugins,
            })
        return result

    def get_hooks(self, event: str) -> List[Callable]:
        return self._hook_registry.get_hooks(event)

    async def trigger_hooks(self, event: str, *args, **kwargs) -> List[Any]:
        return await self._hook_registry.trigger(event, *args, **kwargs)

    @property
    def loaded_plugins(self) -> Dict[str, PluginContext]:
        return dict(self._loaded_plugins)

    @property
    def hook_registry(self) -> HookRegistry:
        return self._hook_registry
