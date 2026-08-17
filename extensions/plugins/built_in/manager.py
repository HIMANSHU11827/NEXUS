"""Plugin Runtime Manager for NEXUS AI — discovers, validates, loads, and
activates plugins with a full lifecycle, fault isolation, capability gating,
and persistent state.

Lifecycle stages (per :class:`PluginStage`):

    discovered → validated → loading → loaded → initialized → enabled
    enabled    → disabled → enabled
    enabled/disabled/failed → uninstalled
    any stage  → failed

Stages are tracked per plugin in a :class:`PluginRecord` and persisted to
``~/.nexus/plugins/state.json`` (stdlib + atomic write, never raises).

Fault isolation: every plugin action (load / init / run hook / tool) is
individually try/except'd so a crashing plugin never kills the core and never
prevents other plugins from loading.  A plugin that errors three times
consecutively during a session is auto-disabled with reason ``crash_loop``.

Capabilities: each plugin declares (from its metadata manifest or the legacy
default in ``trust.py``) a capability allowlist.  ``PluginRecord.capabilities``
gates registrations — a plugin that tries to register a tool/hook/command for
a capability it was not granted is denied at the registration boundary.

Dependency isolation: plugin imports stay lazy and per-plugin; no third-party
dependency is imported at module top, and a plugin missing a dependency fails
that plugin only.
"""

import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from extensions.plugins.built_in.trust import (
    LEGACY_DEFAULT_CAPABILITIES,
    is_bundled_plugin_dir,
    is_user_plugin_load_allowed,
    resolve_capabilities,
)
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.registry import ToolEntry
from tools.nexus_tools.result import ToolCallResult, normalize_result
from utils.singleton import ThreadSafeSingleton

logger = logging.getLogger(__name__)


# ── Lifecycle model ────────────────────────────────────────────────────────

class PluginStage(Enum):
    """Stable, persisted lifecycle stages for a plugin record."""

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    LOADING = "loading"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"
    FAILED = "failed"


#: Consecutive faults (load / hook / tool) that trigger a crash-loop auto-disable.
CRASH_LOOP_THRESHOLD = 3


def _fingerprint(source: str, plugin_dir: str, version: str, capabilities) -> str:
    """Deterministic fingerprint identifying a plugin location + manifest.

    Persisted state is only restored when the fingerprint matches, so stale
    state from a different plugin with the same name (or a rewritten plugin) is
    never misapplied.
    """
    try:
        caps = ",".join(sorted(str(c) for c in (capabilities or ())))
        payload = "|".join([str(source), str(plugin_dir), str(version), caps])
        return hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()
    except Exception:
        return ""


class PluginRecord:
    """Per-plugin lifecycle record: state, capabilities, and fault history."""

    def __init__(
        self,
        name: str,
        source: str = "",
        version: str = "",
        description: str = "",
        plugin_dir: str = "",
        capabilities: Optional[Any] = None,
        state: Optional[PluginStage] = None,
    ) -> None:
        self.name = name
        self.state = state or PluginStage.DISCOVERED
        self.source = source
        self.version = version
        self.description = description
        self.plugin_dir = plugin_dir
        self.capabilities: frozenset = frozenset(capabilities or ())
        # Session-scoped fault bookkeeping (reset per manager instance).
        self.consecutive_errors = 0
        self.last_error = ""
        self.last_error_at = 0.0
        # Disable/uninstall reason, e.g. ``crash_loop``, ``manual``.
        self.reason = ""
        # Registered artifacts, for audit and completeness of unregister.
        self.registered_tools = set()
        self.registered_hooks = set()
        self.registered_commands = set()
        # Transition history: [{"stage": "...", "at": <epoch>}, ...]
        self.history: List[Dict[str, Any]] = []
        # Live context, present while the plugin is loaded.
        self.context: Optional["PluginContext"] = None

    def transition(self, stage: PluginStage, reason: str = "") -> None:
        """Move to ``stage`` and append a timestamped history entry."""
        self.state = stage
        if reason:
            self.reason = reason
        self.history.append({"stage": stage.value, "at": time.time()})
        if len(self.history) > 64:
            del self.history[:-64]

    def fingerprint(self) -> str:
        return _fingerprint(self.source, self.plugin_dir, self.version, self.capabilities)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason or "",
            "source": self.source,
            "version": self.version,
            "description": self.description,
            "plugin_dir": self.plugin_dir,
            "capabilities": sorted(str(c) for c in self.capabilities),
            "fingerprint": self.fingerprint(),
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error or "",
            "last_error_at": self.last_error_at,
            "history": list(self.history),
            "registered_tools": sorted(self.registered_tools),
            "registered_hooks": sorted(self.registered_hooks),
            "registered_commands": sorted(self.registered_commands),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore persistable fields.  Fault count stays session-scoped."""
        state_str = str(data.get("state", "")).strip()
        if state_str:
            for stage in PluginStage:
                if stage.value == state_str:
                    self.state = stage
                    break
        self.reason = data.get("reason", "") or ""
        self.source = data.get("source", self.source) or ""
        self.version = data.get("version", self.version) or ""
        self.description = data.get("description", self.description) or ""
        caps = data.get("capabilities") or []
        if caps:
            self.capabilities = frozenset(str(c) for c in caps)
        self.last_error = data.get("last_error", "") or ""
        self.last_error_at = data.get("last_error_at", 0) or 0
        history = data.get("history") or []
        if isinstance(history, list):
            self.history = [
                {"stage": h.get("stage", ""), "at": h.get("at", 0)}
                for h in history
                if isinstance(h, dict)
            ]


# ── Hook / tool adapters ───────────────────────────────────────────────────

class PluginToolAdapter(BaseTool):
    """Adapts a plugin tool handler into a BaseTool for the ToolRegistry."""

    def __init__(
        self,
        name: str,
        handler: Callable,
        root_dir: Optional[str] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(root_dir)
        self.name = name
        self._handler = handler
        # Optional fault callback used by the manager's crash-loop tracking.
        self._on_error = on_error

    @staticmethod
    def _error_text(result: Dict[str, Any]) -> str:
        """Extract a bounded human-readable error from MCP-style plugin data."""
        value = result.get("error") or result.get("message") or result.get("content")
        if isinstance(value, list):
            value = "\n".join(
                str(item.get("text", item)) if isinstance(item, dict) else str(item)
                for item in value
            )
        return str(value or "Plugin tool reported an error")[:4000]

    def _normalize_plugin_result(self, result: Any) -> ToolCallResult:
        """Canonicalize every plugin return before it reaches core execution."""
        raw = result
        if isinstance(result, dict) and result.get("isError") is True:
            raw = dict(result)
            raw["status"] = "error"
            raw.setdefault("error", self._error_text(raw))
        return normalize_result(
            raw,
            name=self.name,
            tool_call_id="",
            started_at="",
            monotonic_start=time.monotonic(),
            max_output_chars=0,
        )

    def _normalize_stream_chunk(self, chunk: Any) -> Any:
        """Validate stream chunks while preserving ordinary incremental text."""
        normalized = self._normalize_plugin_result(chunk)
        if isinstance(chunk, str) and normalized.success:
            return normalized.output
        return normalized

    async def execute(self, **kwargs) -> ToolResult:
        try:
            if inspect.iscoroutinefunction(self._handler):
                result = await self._handler(**kwargs)
            else:
                result = await asyncio.to_thread(self._handler, **kwargs)
            return self._normalize_plugin_result(result)
        except Exception as e:
            logger.warning(f"Plugin tool '{self.name}' error: {e}")
            if self._on_error is not None:
                try:
                    self._on_error(str(e))
                except Exception:
                    logger.debug("Plugin tool on_error callback failed", exc_info=True)
            return ToolResult(success=False, error=str(e))

    async def stream_execute(self, **kwargs):
        """Stream generator-based plugin output; adapt ordinary handlers safely."""
        try:
            if inspect.isasyncgenfunction(self._handler):
                async for chunk in self._handler(**kwargs):
                    yield self._normalize_stream_chunk(chunk)
                return
            if inspect.isgeneratorfunction(self._handler):
                iterator = self._handler(**kwargs)
                sentinel = object()
                while True:
                    chunk = await asyncio.to_thread(next, iterator, sentinel)
                    if chunk is sentinel:
                        break
                    yield self._normalize_stream_chunk(chunk)
                return
            result = await self.execute(**kwargs)
            yield result
        except Exception as e:
            # A streaming plugin failure degrades to an error chunk instead of
            # propagating into the core loop.
            logger.warning(f"Plugin tool '{self.name}' stream error: {e}")
            if self._on_error is not None:
                try:
                    self._on_error(str(e))
                except Exception:
                    logger.debug("Plugin tool on_error callback failed", exc_info=True)
            yield ToolResult(success=False, error=str(e))


class HookRegistry:
    """Stores and invokes plugin lifecycle hook callbacks.

    ``trigger`` is individually try/except'd per callback (one crashing plugin
    never stops the others) and returns a list of results.  ``pre_tool_call``
    style block directives are normalized to a structured
    ``{"action": "block", "reason": "..."}`` decision so callers can honor (or
    ignore) them instead of silently discarding the veto.
    """

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
        # Optional per-callback owner bookkeeping for fault attribution.
        self._owners: Dict[Callable, str] = {}
        # Optional fault handler called as ``on_fault(owner, event, error)``.
        self.on_fault = None

    def register(self, event: str, cb: Callable, owner: Optional[str] = None) -> None:
        if event not in self._callbacks:
            logger.warning(f"Unknown hook event: {event}. Valid: {self.PLUGIN_EVENTS}")
            return
        with self._lock:
            self._callbacks[event].append(cb)
            if owner:
                self._owners[cb] = owner

    def unregister(self, event: str, cb: Callable) -> bool:
        if event not in self._callbacks:
            return False
        with self._lock:
            callbacks = self._callbacks[event]
            try:
                callbacks.remove(cb)
                self._owners.pop(cb, None)
                return True
            except ValueError:
                return False

    def get_hooks(self, event: str) -> List[Callable]:
        return list(self._callbacks.get(event, []))

    @staticmethod
    def _normalize_result(result: Any) -> Any:
        """Surface hook block decisions as a structured ``{action, reason}``.

        Both ``{"action": "block"}`` and ``{"block": True}`` shapes are accepted
        (matching what orchestrators/v5/tools.py parses).  Non-block returns are
        passed through untouched for backward compatibility.
        """
        if isinstance(result, dict):
            blocked = result.get("action") == "block" or result.get("block") is True
            if blocked:
                reason = result.get("reason") or result.get("message") or "Blocked by plugin hook."
                return {"action": "block", "reason": str(reason)}
        return result

    async def trigger(self, event: str, *args, **kwargs) -> List[Any]:
        results: List[Any] = []
        cbs = list(self._callbacks.get(event, []))
        for cb in cbs:
            try:
                if inspect.iscoroutinefunction(cb):
                    value = await cb(*args, **kwargs)
                else:
                    value = await asyncio.to_thread(cb, *args, **kwargs)
                results.append(self._normalize_result(value))
            except Exception as e:
                logger.warning(f"Plugin hook '{event}' callback error: {e}")
                owner = self._owners.get(cb)
                if owner and callable(self.on_fault):
                    try:
                        self.on_fault(owner, event, e)
                    except Exception:
                        logger.debug("HookRegistry on_fault handler failed", exc_info=True)
        return results


class PluginContext:
    """Context passed to a plugin's register() function for integration.

    Capability gating: every registration method checks the plugin's granted
    capability allowlist first and denies (softly, returning False) when the
    required capability was not granted.
    """

    def __init__(
        self,
        plugin_name: str,
        plugin_dir: str,
        kernel,
        hook_registry: HookRegistry,
        capabilities: Optional[Any] = None,
        on_fault: Optional[Callable[..., None]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._name = plugin_name
        self._dir = plugin_dir
        self._kernel = kernel
        self._hooks = hook_registry
        # Fail closed: capabilities default to the legacy in-process integration
        # surface; explicit manifests pass their resolved allowlist instead.
        self._capabilities: frozenset = frozenset(
            capabilities if capabilities is not None else LEGACY_DEFAULT_CAPABILITIES
        )
        self._on_fault = on_fault
        self._meta = meta or {}
        self._cli_commands: Dict[str, Callable] = {}
        self._registered_tools: Dict[str, PluginToolAdapter] = {}
        self._registered_hooks: List[tuple[str, Callable]] = []
        self._denied: List[Dict[str, str]] = []

    # ── capability enforcement ─────────────────────────────────────────────

    @property
    def capabilities(self) -> frozenset:
        return frozenset(self._capabilities)

    def _allowed(self, capability: str) -> bool:
        return capability in self._capabilities

    def _deny(self, kind: str, name: str, capability: str) -> None:
        self._denied.append({"kind": kind, "name": str(name), "capability": capability})
        logger.warning(
            "[PLUGIN:%s] Denied %s '%s': capability '%s' not granted (allowed: %s)",
            self._name,
            kind,
            name,
            capability,
            ",".join(sorted(self._capabilities)) or "<none>",
        )

    @property
    def denied_registrations(self) -> List[Dict[str, str]]:
        return list(self._denied)

    # ── registration (capability-gated) ────────────────────────────────────

    def register_tool(self, name: str, schema: dict, handler: Callable) -> bool:
        if not self._allowed("tools"):
            self._deny("tool", name, "tools")
            return False
        if self._kernel is None:
            self._deny("tool", name, "tools")
            logger.warning(
                "[PLUGIN:%s] Denied tool '%s': kernel tools registry unavailable",
                self._name,
                name,
            )
            return False
        adapter = PluginToolAdapter(
            name,
            handler,
            root_dir=self._dir,
            on_error=self._fault_cb("tool"),
        )
        if name in self._kernel.tools._tools and name not in self._registered_tools:
            self._deny("tool", name, "tools")
            logger.warning(
                "[PLUGIN:%s] Denied tool '%s': name already registered by another plugin",
                self._name,
                name,
            )
            return False
        entry = ToolEntry(name=name, schema=schema, instance=adapter)
        self._kernel.tools._tools[name] = entry
        self._registered_tools[name] = adapter
        logger.info(f"[PLUGIN:{self._name}] Registered tool: {name}")
        return True

    def register_hook(self, event: str, callback: Callable) -> bool:
        if not self._allowed("hooks"):
            self._deny("hook", event, "hooks")
            return False
        before = len(self._hooks.get_hooks(event))
        self._hooks.register(event, callback, owner=self._name)
        after = len(self._hooks.get_hooks(event))
        if after > before:
            self._registered_hooks.append((event, callback))
        logger.info(f"[PLUGIN:{self._name}] Registered hook: {event}")
        return True

    def register_cli_command(self, name: str, handler: Callable) -> bool:
        if not self._allowed("cli"):
            self._deny("cli", name, "cli")
            return False
        self._cli_commands[name] = handler
        logger.info(f"[PLUGIN:{self._name}] Registered CLI command: {name}")
        return True

    def _fault_cb(self, kind: str) -> Optional[Callable[[str], None]]:
        """Return an error callback for crash-loop bookkeeping, if any."""
        if self._on_fault is None:
            return None

        def _call(error: str) -> None:
            try:
                self._on_fault(kind, error)
            except Exception:
                logger.debug("[PLUGIN:%s] fault callback failed", self._name, exc_info=True)

        return _call

    # ── configuration / inspection ─────────────────────────────────────────

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
    """Discovers, validates, loads, enables, disables, and uninstalls plugins.

    Every operation is guarded so a single misbehaving plugin — a crashing
    ``register()``, hook, or tool — never kills the core and never blocks other
    plugins from loading.  Plugins are tracked in ``PluginRecord`` instances
    persisted to ``~/.nexus/plugins/state.json``.
    """

    # class-level fake so __init__ never fails before our flags exist
    _initialized: bool = False

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
        self._hook_registry.on_fault = self._hook_fault_handler
        self._loaded_plugins: Dict[str, PluginContext] = {}
        self._discovered: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._ensure_records()

        self._ensure_dirs()
        self.discover_plugins()

    # ── internal plumbing ──────────────────────────────────────────────────

    def _ensure_records(self) -> None:
        """Initialize in-memory record stores if not already present."""
        if not hasattr(self, "_lock") or self._lock is None:
            self._lock = threading.RLock()
        # The PluginManager is a ThreadSafeSingleton, so ``PluginManager.__new__``
        # (used by tests to build an "uninitialized" manager) actually returns the
        # shared singleton instance.  Detect when the plugin search roots changed
        # (each test swaps in its own temp dirs) and start with fresh record state
        # so stale disabled/crash-loop state from another directory is never applied.
        tag = (
            getattr(self, "_bundled_dir", None),
            getattr(self, "_user_dir", None),
        )
        env_changed = (
            getattr(self, "_records_env_tag", None) is not None
            and self._records_env_tag != tag
        )
        if env_changed:
            self._records = {}
            self._state_cache = {}
            self._state_loaded = False
        if not hasattr(self, "_records") or self._records is None:
            self._records: Dict[str, PluginRecord] = {}
        if not hasattr(self, "_state_cache") or self._state_cache is None:
            self._state_cache: Dict[str, Dict[str, Any]] = {}
        if not hasattr(self, "_state_loaded") or not self._state_loaded:
            self._state_loaded = False
        self._records_env_tag = tag

    def _state_path(self) -> str:
        """State file location: override → env → ``~/.nexus/plugins/state.json``."""
        if getattr(self, "_state_path_override", None):
            return self._state_path_override
        env = os.environ.get("NEXUS_PLUGIN_STATE_FILE")
        if env:
            return env
        user_dir = getattr(self, "_user_dir", None) or os.path.join(
            os.path.expanduser("~"), ".nexus", "plugins"
        )
        return os.path.join(user_dir, "state.json")

    def _load_state_cache(self) -> Dict[str, Dict[str, Any]]:
        """Lazily read the persisted state file.  Never raises."""
        self._ensure_records()
        if self._state_loaded:
            return self._state_cache
        self._state_loaded = True
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
            self._state_cache = {k: v for k, v in plugins.items() if isinstance(v, dict)}
        except FileNotFoundError:
            self._state_cache = {}
        except Exception as e:
            logger.warning(f"Failed to load plugin state: {e}")
            self._state_cache = {}
        return self._state_cache

    def _save_state(self) -> None:
        """Atomically persist every record to ``state.json``.  Never raises."""
        self._ensure_records()
        data: Dict[str, Any] = {"_version": 1, "plugins": {}}
        for name, rec in self._records.items():
            try:
                data["plugins"][name] = rec.to_dict()
            except Exception as e:
                logger.warning(f"Failed to serialize plugin '{name}' state: {e}")
        state_path = self._state_path()
        try:
            os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
            tmp_path = state_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp_path, state_path)
        except Exception as e:
            logger.warning(f"Failed to save plugin state: {e}")

    def _ensure_dirs(self) -> None:
        os.makedirs(self._bundled_dir, exist_ok=True)
        os.makedirs(self._user_dir, exist_ok=True)

    # ── record management ──────────────────────────────────────────────────

    def _record_for(
        self,
        name: str,
        plugin_dir: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PluginRecord:
        """Return (creating if needed) the lifecycle record for ``name``.

        Restores persisted state only when the plugin's fingerprint matches, so
        state from a previous session is applied to the same plugin location but
        never to a different plugin that happens to share a name.
        """
        self._ensure_records()
        rec = self._records.get(name)
        if rec is None:
            source = ""
            if plugin_dir:
                try:
                    source = (
                        "bundled"
                        if is_bundled_plugin_dir(plugin_dir, self._bundled_dir)
                        else "user"
                    )
                except Exception:
                    source = "user"
            capabilities = resolve_capabilities(meta) if meta else ()
            rec = PluginRecord(name=name, plugin_dir=plugin_dir or "", source=source)
            if meta:
                rec.version = meta.get("version", "0.0.0")
                rec.description = meta.get("description", "")
                rec.capabilities = resolve_capabilities(meta)
            persisted = self._load_state_cache().get(name)
            if isinstance(persisted, dict) and persisted.get("fingerprint") == rec.fingerprint():
                rec.from_dict(persisted)
            self._records[name] = rec
            return rec
        if meta is not None:
            rec.version = meta.get("version", rec.version) or rec.version
            rec.description = meta.get("description", rec.description) or rec.description
            if plugin_dir:
                rec.plugin_dir = plugin_dir
                try:
                    rec.source = (
                        "bundled"
                        if is_bundled_plugin_dir(plugin_dir, self._bundled_dir)
                        else "user"
                    )
                except Exception:
                    pass
            rec.capabilities = resolve_capabilities(meta, rec.capabilities)
        return rec

    def get_plugin_record(self, name: str) -> Optional[PluginRecord]:
        """Return the lifecycle record for ``name``, or None."""
        self._ensure_records()
        return self._records.get(name)

    def plugin_records(self) -> List[Dict[str, Any]]:
        """Return a serializable snapshot of every lifecycle record."""
        self._ensure_records()
        return [rec.to_dict() for rec in self._records.values()]

    # ── discovery / metadata ───────────────────────────────────────────────

    def discover_plugins(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_records()
            self._discovered = []
            for source_dir, source in ((self._bundled_dir, "bundled"), (self._user_dir, "user")):
                if not os.path.isdir(source_dir):
                    continue
                try:
                    entries = os.listdir(source_dir)
                except OSError as e:
                    logger.warning("Cannot list plugin source '%s': %s", source_dir, e)
                    continue
                for name in entries:
                    plugin_dir = os.path.join(source_dir, name)
                    if not os.path.isdir(plugin_dir):
                        continue
                    meta = self._read_meta(plugin_dir, name)
                    if meta:
                        meta["source"] = source
                        self._discovered.append(meta)
                        rec = self._record_for(name, plugin_dir, meta)
                        # A manifest that marks the plugin inactive is treated as
                        # operator-disabled at discovery time.
                        if meta.get("active") is False and rec.state not in (
                            PluginStage.DISABLED,
                            PluginStage.UNINSTALLED,
                        ):
                            rec.transition(PluginStage.DISABLED, reason="meta_inactive")
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

    def _find_plugin_dir(self, name: str) -> Optional[str]:
        for source_dir in (self._bundled_dir, self._user_dir):
            plugin_dir = os.path.join(source_dir, name)
            if os.path.isdir(plugin_dir):
                meta_path = os.path.join(plugin_dir, f"{name}.json")
                if os.path.isfile(meta_path):
                    return plugin_dir
        return None

    # ── lifecycle operations ───────────────────────────────────────────────

    def validate_plugin(self, name: str) -> bool:
        """Validate plugin source + metadata; transition to ``validated``/``failed``."""
        with self._lock:
            plugin_dir = self._find_plugin_dir(name)
            rec = self._record_for(name, plugin_dir=plugin_dir)
            if not plugin_dir:
                self._fail(rec, "validation: plugin directory not found")
                return False
            meta = self._read_meta(plugin_dir, name)
            if meta is None:
                self._fail(rec, "validation: missing or invalid metadata")
                return False
            if not os.path.isfile(os.path.join(plugin_dir, "__init__.py")):
                self._fail(rec, "validation: missing __init__.py")
                return False
            if meta.get("active") is False:
                if rec.state not in (PluginStage.DISABLED, PluginStage.UNINSTALLED):
                    rec.transition(PluginStage.DISABLED, reason="meta_inactive")
                self._save_state()
                return False
            rec.source = rec.source
            rec.transition(PluginStage.VALIDATED)
            self._save_state()
            return True

    def load_plugin(self, name: str, force: bool = False) -> bool:
        """Load and activate a plugin.  Returns True on success; never raises."""
        with self._lock:
            self._ensure_records()
            if name in self._loaded_plugins:
                rec = self.get_plugin_record(name)
                if rec is not None and rec.state != PluginStage.ENABLED:
                    rec.transition(PluginStage.ENABLED)
                    self._save_state()
                return True

            plugin_dir = self._find_plugin_dir(name)
            if not plugin_dir:
                rec = self._record_for(name)
                self._fail(rec, "Plugin directory not found")
                return False

            meta = self._read_meta(plugin_dir, name)
            rec = self._record_for(name, plugin_dir=plugin_dir, meta=meta)
            if meta is None:
                logger.warning(f"Plugin '{name}' has invalid or missing metadata")
                self._fail(rec, "invalid or missing metadata")
                return False

            if meta.get("active") is False:
                logger.warning(f"Plugin '{name}' is disabled by metadata")
                if rec.state not in (PluginStage.DISABLED, PluginStage.UNINSTALLED):
                    rec.transition(PluginStage.DISABLED, reason="meta_inactive")
                self._save_state()
                return False

            # A plugin that was explicitly disabled/uninstalled stays off unless
            # the caller forces a load (enable_plugin does).
            if not force and rec.state in (PluginStage.DISABLED, PluginStage.UNINSTALLED):
                logger.warning(
                    "Plugin '%s' is '%s'; call enable_plugin() to load it",
                    name,
                    rec.state.value,
                )
                return False

            init_path = os.path.join(plugin_dir, "__init__.py")
            if not os.path.isfile(init_path):
                logger.warning(f"Plugin '{name}' has no __init__.py")
                self._fail(rec, "missing __init__.py")
                return False

            if not is_bundled_plugin_dir(plugin_dir, self._bundled_dir) and not is_user_plugin_load_allowed():
                logger.warning(
                    "Refusing to load user plugin '%s': plugin source is executable code. "
                    "Set NEXUS_ALLOW_USER_PLUGIN_LOAD=1 only after reviewing it.",
                    name,
                )
                self._fail(rec, "user plugin load not allowed")
                return False

            if rec.state in (PluginStage.DISCOVERED, PluginStage.FAILED, PluginStage.LOADED,
                             PluginStage.INITIALIZED, PluginStage.ENABLED):
                rec.transition(PluginStage.VALIDATED)
            rec.transition(PluginStage.LOADING)
            ctx = None
            try:
                default_capabilities = resolve_capabilities(meta, rec.capabilities)
                ctx = PluginContext(
                    name,
                    plugin_dir,
                    getattr(self, "_kernel", None),
                    self._hook_registry,
                    capabilities=default_capabilities,
                    on_fault=self._plugin_fault_handler(name),
                    meta=meta,
                )
                spec = importlib.util.spec_from_file_location(f"nexus_plugin_{name}", init_path)
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"Could not create module spec for '{name}'")
                mod = importlib.util.module_from_spec(spec)
                # Per-plugin import isolation: exceptions (e.g. a missing
                # dependency) fail this plugin only.
                spec.loader.exec_module(mod)
                rec.transition(PluginStage.LOADED)
                if not hasattr(mod, "register"):
                    logger.warning(f"Plugin '{name}' has no register() function")
                    self._fail(rec, "no register() function")
                    return False
                mod.register(ctx)
                rec.transition(PluginStage.INITIALIZED)
                self._loaded_plugins[name] = ctx
                rec.context = ctx
                rec.consecutive_errors = 0
                rec.reason = ""
                rec.registered_tools = set(ctx.registered_tools)
                rec.registered_hooks = {event for event, _ in ctx.registered_hooks}
                rec.registered_commands = set(ctx.cli_commands)
                rec.capabilities = ctx.capabilities
                rec.transition(PluginStage.ENABLED)
                self._save_state()
                logger.info(f"[PLUGIN] Loaded: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to load plugin '{name}': {e}")
                if ctx is not None:
                    self._unregister_all(ctx, name)
                self._fail(rec, str(e))
                return False

    def enable_plugin(self, name: str) -> bool:
        """Enable a plugin, loading it if needed.  Returns True on success."""
        with self._lock:
            rec = self.get_plugin_record(name)
            if rec is None:
                self.validate_plugin(name)
                rec = self.get_plugin_record(name)
            if rec is None:
                return False
            if rec.state == PluginStage.ENABLED or name in self._loaded_plugins:
                if rec.state != PluginStage.ENABLED:
                    rec.transition(PluginStage.ENABLED)
                    self._save_state()
                return True
            return self.load_plugin(name, force=True)

    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin and unregister all of its live artifacts."""
        with self._lock:
            self._ensure_records()
            rec = self._records.get(name)
            if rec is None:
                return False
            ctx = self._loaded_plugins.get(name) or rec.context
            if ctx is not None:
                self._unregister_all(ctx, name)
                self._loaded_plugins.pop(name, None)
            rec.context = None
            if rec.state != PluginStage.DISABLED:
                rec.transition(PluginStage.DISABLED, reason=rec.reason or "manual")
            else:
                rec.reason = rec.reason or "manual"
            self._save_state()
            logger.info(f"[PLUGIN] Disabled: {name}")
            return True

    def unload_plugin(self, name: str) -> bool:
        """Backward-compatible unload: disable + fully unregister artifacts."""
        return self.disable_plugin(name)

    def uninstall_plugin(self, name: str) -> bool:
        """Uninstall a plugin: unregister everything and mark it uninstalled."""
        with self._lock:
            self._ensure_records()
            plugin_dir = self._find_plugin_dir(name)
            rec = self._record_for(name, plugin_dir=plugin_dir)
            ctx = self._loaded_plugins.get(name)
            if ctx is not None:
                self._unregister_all(ctx, name)
                self._loaded_plugins.pop(name, None)
            rec.context = None
            rec.registered_tools.clear()
            rec.registered_hooks.clear()
            rec.registered_commands.clear()
            rec.transition(PluginStage.UNINSTALLED, reason="uninstalled")
            self._save_state()
            logger.info(f"[PLUGIN] Uninstalled: {name}")
            return True

    # ── unregister / fault handling ────────────────────────────────────────

    def _unregister_all(self, ctx: PluginContext, name: str) -> None:
        """Remove every tool / hook / CLI command a plugin registered."""
        tools = getattr(getattr(self._kernel, "tools", None), "_tools", {}) if self._kernel else {}
        for tool_name, adapter in ctx.registered_tools.items():
            entry = tools.get(tool_name) if isinstance(tools, dict) else None
            if entry is not None and getattr(entry, "instance", None) is adapter:
                del tools[tool_name]
                logger.info(f"[PLUGIN:{name}] Unregistered tool: {tool_name}")
        for event, callback in ctx.registered_hooks:
            if self._hook_registry.unregister(event, callback):
                logger.info(f"[PLUGIN:{name}] Unregistered hook: {event}")
        if getattr(ctx, "_cli_commands", None):
            ctx._cli_commands.clear()
            logger.info(f"[PLUGIN:{name}] Unregistered CLI commands")
        rec = self._records.get(name)
        if rec is not None:
            rec.registered_tools.clear()
            rec.registered_hooks.clear()
            rec.registered_commands.clear()

    def _fail(self, rec: PluginRecord, message: str) -> None:
        """Mark a plugin failed and record the fault for crash-loop tracking."""
        rec.last_error = message
        rec.last_error_at = time.time()
        rec.reason = message
        rec.transition(PluginStage.FAILED)
        self.record_fault(rec.name, where="load", error=message)

    def record_fault(self, name: str, where: str = "runtime", error: str = "") -> None:
        """Count a fault for a plugin; auto-disable after 3 consecutive errors."""
        self._ensure_records()
        with self._lock:
            rec = self._records.get(name)
            if rec is None:
                return
            rec.consecutive_errors += 1
            rec.last_error = f"[{where}] {error}" if error else f"[{where}]"
            rec.last_error_at = time.time()
            if rec.consecutive_errors >= CRASH_LOOP_THRESHOLD:
                logger.info(
                    "[PLUGIN] Auto-disabling '%s': crash_loop after %d consecutive errors",
                    name,
                    rec.consecutive_errors,
                )
                self._disable(name, reason="crash_loop")
                return
            self._save_state()

    def record_success(self, name: str) -> None:
        """Reset a plugin's consecutive-error counter after a successful action."""
        self._ensure_records()
        with self._lock:
            rec = self._records.get(name)
            if rec is not None and rec.consecutive_errors:
                rec.consecutive_errors = 0
                self._save_state()

    def _disable(self, name: str, reason: str = "") -> None:
        """Internal disable used by crash-loop auto-disable (no return gate)."""
        ctx = self._loaded_plugins.get(name)
        if ctx is not None:
            self._unregister_all(ctx, name)
            self._loaded_plugins.pop(name, None)
        rec = self._records.get(name)
        if rec is not None:
            rec.context = None
            rec.registered_tools.clear()
            rec.registered_hooks.clear()
            rec.registered_commands.clear()
            if rec.state != PluginStage.DISABLED:
                rec.transition(PluginStage.DISABLED, reason=reason or rec.reason or "crash_loop")
            else:
                rec.reason = reason or rec.reason or "crash_loop"
        self._save_state()

    def _plugin_fault_handler(self, name: str):
        """Return a bound fault callback for one plugin's interfaces."""
        def _handle(kind: str, error: Any) -> None:
            self.record_fault(name, where=kind, error=str(error))

        return _handle

    def _hook_fault_handler(self, owner: str, event: str, error: Any) -> None:
        """HookRegistry.on_fault entry point attributing errors to a plugin."""
        self.record_fault(owner, where=f"hook:{event}", error=str(error))

    # ── public query API (backward compatible) ─────────────────────────────

    def list_plugins(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        with self._lock:
            for meta in self._discovered:
                name = meta.get("name", "")
                rec = self._records.get(name)
                active = meta.get("active", True) is not False
                if rec is not None and rec.state in (PluginStage.DISABLED, PluginStage.UNINSTALLED):
                    active = False
                result.append({
                    "name": name,
                    "version": meta.get("version", "0.0.0"),
                    "description": meta.get("description", ""),
                    "source": meta.get("source", ""),
                    "active": active,
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
