"""ToolRegistry — discovers and manages NEXUS tools from tools/<name>/."""

import asyncio
import importlib
import inspect
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Dict, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("NEXUS_TOOL_REGISTRY")


def _policy_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "on", "1"}:
        return True
    if normalized in {"false", "no", "off", "0"}:
        return False
    return default


def _policy_int(value: Any, default: int = 0, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _policy_list(value: Any) -> list:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\n", ";").split(";") if item.strip()]
    return []


class ToolEntry:
    """Represents a registered tool with its metadata and handler instance."""

    def __init__(self, name: str, schema: dict, instance: Any, check_fn=None, requires_env: Optional[list] = None):
        self.name = name
        self.schema = schema
        self.instance = instance
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.constitution = schema.get("constitution") or {}
        runtime = schema.get("execution") or schema.get("runtime") or {}
        self.execution = {
            **(self.constitution if isinstance(self.constitution, dict) else {}),
            **(runtime if isinstance(runtime, dict) else {}),
        }
        self.enabled = _policy_bool(self.execution.get("enabled", schema.get("enabled", True)), True)
        self.intent = self.execution.get("intent", "")
        self.rules = _policy_list(self.execution.get("rules", schema.get("rules", [])))
        self.conditions = _policy_list(self.execution.get("conditions", schema.get("conditions", [])))
        self.one_time_use = _policy_bool(
            self.execution.get("one_time_use", self.execution.get("oneTimeUse", False)),
            False,
        )
        self.max_per_task = _policy_int(
            self.execution.get("max_per_task", self.execution.get("maxPerTask", 0)),
            0,
            0,
        )
        max_parallel = self.execution.get("max_parallel", self.execution.get("maxParallel", 1))
        self.max_parallel = _policy_int(max_parallel, 1, 1)
        cooldown = self.execution.get("cooldown_ms", self.execution.get("cooldownMs", 0))
        self.cooldown_ms = _policy_int(cooldown, 0, 0)
        self._semaphore = asyncio.Semaphore(self.max_parallel)
        self._cooldown_lock = asyncio.Lock()
        self._last_started_at = 0.0

    def is_available(self) -> bool:
        """Check if this tool is available in the current environment.

        Checks:
        1. ``check_fn`` — custom availability check (e.g. API key presence)
        2. ``requires_env`` — required env vars must be set

        Returns True if available, False if not.
        """
        if not self.enabled:
            return False
        # check_fn takes priority
        if self.check_fn is not None:
            try:
                return bool(self.check_fn())
            except Exception:
                return False
        # requires_env check
        if self.requires_env:
            for var in self.requires_env:
                if not os.environ.get(var):
                    return False
        return True

    def availability(self) -> Dict[str, Any]:
        """Return a user-facing availability explanation for this tool."""
        if not self.enabled:
            return {"available": False, "reason": "disabled", "missing_env": []}

        missing_env = [var for var in self.requires_env if not os.environ.get(var)]
        if self.check_fn is not None:
            try:
                check_ok = bool(self.check_fn())
            except Exception:
                return {"available": False, "reason": "check_failed", "missing_env": missing_env}
            if not check_ok:
                reason = "missing_env" if missing_env else "check_failed"
                return {"available": False, "reason": reason, "missing_env": missing_env}

        if missing_env:
            return {"available": False, "reason": "missing_env", "missing_env": missing_env}

        return {"available": True, "reason": "ready", "missing_env": []}

    def is_read_only(self, params=None) -> bool:
        if self.instance and hasattr(self.instance, "is_read_only"):
            try:
                # support both no-args and args signatures
                sig = inspect.signature(self.instance.is_read_only)
                if len(sig.parameters) == 0:
                    return self.instance.is_read_only()
                return self.instance.is_read_only(params)
            except Exception:
                logger.warning("tools/nexus_tools/registry.py:56 is_read_only: suppressed error", exc_info=True)
                pass
        name_lower = self.name.lower()
        return any(x in name_lower for x in ("read", "view", "search", "grep", "glob", "get", "find", "list", "status", "health"))

    def is_concurrency_safe(self) -> bool:
        if "parallel" in self.execution:
            return bool(self.execution.get("parallel"))
        if self.max_parallel > 1:
            return True
        if self.instance and hasattr(self.instance, "is_concurrency_safe"):
            try:
                return self.instance.is_concurrency_safe()
            except Exception:
                logger.warning("tools/nexus_tools/registry.py:65 is_concurrency_safe: suppressed error", exc_info=True)
                pass
        return self.is_read_only()

    async def wait_for_cooldown(self) -> None:
        if self.cooldown_ms <= 0:
            return
        async with self._cooldown_lock:
            now = time.monotonic()
            wait_for = (self.cooldown_ms / 1000) - (now - self._last_started_at)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_started_at = time.monotonic()


class ToolRegistry:
    """Discovers tools from tools/<name>/ and provides runtime execution."""

    def __init__(self, root: Optional[str] = None):
        self.root = root or os.getcwd()
        self._tools: Dict[str, ToolEntry] = {}
        self._discover()

    @staticmethod
    def _bind_runtime_context(entry: ToolEntry, context: Any) -> None:
        """Pass per-call runtime context to tools that opt into it.

        Tool schemas intentionally do not expose these internal fields to the
        model. The loop injects them after validation so tools such as hive can
        emit real lifecycle events into the active GUI/TUI stream.
        """
        if not context or entry.instance is None:
            return
        binder = getattr(entry.instance, "set_runtime_context", None)
        if not callable(binder):
            return
        try:
            binder(context)
        except Exception:
            logger.warning("Tool runtime context binding failed for %s", entry.name, exc_info=True)

    def _discover(self):
        tools_dir = os.path.join(self.root, "tools")
        if not os.path.isdir(tools_dir):
            return
        for name in os.listdir(tools_dir):
            if name.startswith(("_", ".")) or name == "nexus_tools":
                continue
            tool_dir = os.path.join(tools_dir, name)
            if not os.path.isdir(tool_dir):
                continue
            jsnol = os.path.join(tool_dir, f"{name}.jsnol")
            if not os.path.isfile(jsnol):
                continue
            try:
                with open(jsnol, encoding="utf-8") as f:
                    meta = json.load(f)
                scripts_dir = os.path.join(tool_dir, "scripts")
                handler_cls = None
                if os.path.isdir(scripts_dir):
                    for script in sorted(
                        s for s in os.listdir(scripts_dir)
                        if s.endswith(".py") and not s.startswith("_")
                    ):
                        mod_name = script[:-3]
                        try:
                            spec = importlib.util.spec_from_file_location(
                                mod_name, os.path.join(scripts_dir, script)
                            )
                            if spec and spec.loader:
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                for _, obj in inspect.getmembers(mod, inspect.isclass):
                                    if issubclass(obj, BaseTool) and obj is not BaseTool:
                                        handler_cls = obj
                                        break
                                if handler_cls:
                                    break
                        except Exception:
                            logger.warning(f"Could not load: {os.path.join(scripts_dir, script)}")
                instance = handler_cls(root_dir=self.root) if handler_cls else None
                requires_env = meta.get("requires_env", [])
                check_fn_name = meta.get("check_fn", None)
                check_fn = None
                if check_fn_name and instance and hasattr(instance, check_fn_name):
                    check_fn = getattr(instance, check_fn_name)
                entry = ToolEntry(
                    name=name,
                    schema=meta,
                    instance=instance,
                    check_fn=check_fn,
                    requires_env=requires_env,
                )
                self._tools[name] = entry
                logger.info(f"Registered tool: {name} v{meta.get('version', '?')}")
            except Exception as e:
                logger.error(f"Failed to register tool '{name}': {e}")

    def get(self, name: str) -> Optional[ToolEntry]:
        return self._tools.get(name)

    @staticmethod
    def _apply_defaults(entry: ToolEntry, params: Dict[str, Any]) -> None:
        defaults = entry.execution.get("defaults") or entry.schema.get("defaults") or {}
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                params.setdefault(key, value)

        definitions = entry.schema.get("params") or {}
        if isinstance(definitions, dict):
            for param_name, definition in definitions.items():
                if isinstance(definition, dict) and "default" in definition:
                    params.setdefault(param_name, definition["default"])

    @staticmethod
    def _coerce_params(entry: ToolEntry, params: Dict[str, Any]) -> None:
        """Coerce safe scalar values from model/tool-call text into schema types."""
        definitions = entry.schema.get("params") or {}
        if not isinstance(definitions, dict):
            return
        for param_name, definition in definitions.items():
            if not isinstance(definition, dict) or param_name not in params or params[param_name] is None:
                continue
            expected_name = definition.get("type")
            value = params[param_name]
            if expected_name == "integer" and isinstance(value, str):
                stripped = value.strip()
                if stripped and stripped.lstrip("-").isdigit():
                    params[param_name] = int(stripped)
            elif expected_name == "number" and isinstance(value, str):
                stripped = value.strip()
                try:
                    params[param_name] = float(stripped)
                except ValueError:
                    pass
            elif expected_name == "boolean" and isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "yes", "on", "1"}:
                    params[param_name] = True
                elif normalized in {"false", "no", "off", "0"}:
                    params[param_name] = False
            elif expected_name == "string" and not isinstance(value, (dict, list)):
                params[param_name] = str(value)

    @staticmethod
    def _validate_params(entry: ToolEntry, params: Dict[str, Any]) -> None:
        """Validate the portable subset of JSON schema used by ``*.jsnol``.

        Tool handlers remain responsible for domain validation.  This boundary
        catches missing and plainly mistyped model arguments before any tool
        code (and therefore any side effect) can run.
        """
        definitions = entry.schema.get("params") or {}
        if not isinstance(definitions, dict):
            raise ValueError(f"Tool '{entry.name}' has an invalid params schema")
        python_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for param_name, definition in definitions.items():
            if not isinstance(definition, dict):
                raise ValueError(f"Tool '{entry.name}' has an invalid schema for '{param_name}'")
            if definition.get("required") and param_name not in params:
                raise ValueError(f"Tool '{entry.name}' requires parameter '{param_name}'")
            if param_name not in params or params[param_name] is None:
                continue
            expected_name = definition.get("type")
            expected_type = python_types.get(expected_name)
            value = params[param_name]
            if expected_type and (
                not isinstance(value, expected_type)
                or expected_name in {"integer", "number"} and isinstance(value, bool)
            ):
                raise TypeError(
                    f"Tool '{entry.name}' parameter '{param_name}' must be {expected_name}"
                )

    @classmethod
    def _prepare_execution(cls, entry: ToolEntry, params: Dict[str, Any]) -> None:
        if not entry.is_available():
            missing = [name for name in entry.requires_env if not os.environ.get(name)]
            detail = f" Missing environment: {', '.join(missing)}." if missing else ""
            raise RuntimeError(f"Tool '{entry.name}' is unavailable.{detail}")
        cls._apply_defaults(entry, params)
        cls._coerce_params(entry, params)
        cls._validate_params(entry, params)

    def list_tools(self, include_unavailable: bool = False) -> Dict[str, Any]:
        result = {}
        for name, entry in self._tools.items():
            availability = entry.availability()
            if not include_unavailable and not availability["available"]:
                continue
            result[name] = {
                "version": entry.schema.get("version", "?"),
                "description": entry.schema.get("description", ""),
                "available": availability["available"],
                "availability_reason": availability["reason"],
                "missing_env": availability["missing_env"],
                "has_handler": entry.instance is not None,
                "constitution": {
                    "intent": entry.intent,
                    "rules": entry.rules,
                    "conditions": entry.conditions,
                    "one_time_use": entry.one_time_use,
                    "max_per_task": entry.max_per_task,
                    "parallel": entry.is_concurrency_safe(),
                    "max_parallel": entry.max_parallel,
                    "cooldown_ms": entry.cooldown_ms,
                },
            }
        return result

    async def execute(self, name: str, **params) -> ToolResult:
        entry = self.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")
        if entry.instance is None:
            raise NotImplementedError(f"Tool '{name}' has no executable handler")
        runtime_context = params.pop("_runtime_context", None)
        self._prepare_execution(entry, params)
        async with entry._semaphore:
            self._bind_runtime_context(entry, runtime_context)
            await entry.wait_for_cooldown()
            return await entry.instance.execute(**params)

    async def stream_execute(self, name: str, **params) -> AsyncGenerator[Any, None]:
        """Universal streaming adapter for built-in, plugin, skill, and MCP tools.

        Native streaming implementations yield immediately. Legacy atomic tools
        yield their real ToolResult once it exists, without fake delayed chunks.
        """
        entry = self.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")
        if entry.instance is None:
            raise NotImplementedError(f"Tool '{name}' has no executable handler")
        runtime_context = params.pop("_runtime_context", None)
        self._prepare_execution(entry, params)

        async with entry._semaphore:
            self._bind_runtime_context(entry, runtime_context)
            await entry.wait_for_cooldown()
            stream_method = getattr(entry.instance, "stream_execute", None)
            if callable(stream_method):
                result = stream_method(**params)
                if inspect.isasyncgen(result):
                    async for chunk in result:
                        yield chunk
                    return
                if inspect.isgenerator(result):
                    sentinel = object()
                    while True:
                        chunk = await asyncio.to_thread(next, result, sentinel)
                        if chunk is sentinel:
                            break
                        yield chunk
                    return
                if inspect.isawaitable(result):
                    yield await result
                    return

            yield await entry.instance.execute(**params)
