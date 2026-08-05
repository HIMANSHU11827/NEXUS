"""ToolRegistry — discovers and manages NEXUS tools from tools/<name>/."""

import asyncio
import importlib
import importlib.util
import inspect
import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.result import (
    DEFAULT_MAX_OUTPUT_CHARS,
    STATUS_BLOCKED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_TIMEOUT,
    STATUS_UNIMPLEMENTED,
    ToolArgumentError,
    ToolCallResult,
    classify_error,
    error_result,
    normalize_result,
    parse_tool_arguments,
    start_envelope,
)

logger = logging.getLogger("NEXUS_TOOL_REGISTRY")

#: Hard default wall-clock budget for a single tool call (milliseconds).
DEFAULT_TOOL_TIMEOUT_MS = 300_000

#: Preview length exposed when an oversized tool output is persisted to disk.
#: The full output is written to ``context_archive/tool-results/<id>.txt`` and
#: the caller sees this many leading characters inside the persist envelope.
PERSIST_PREVIEW_CHARS = 4000


def _result_output_text(result: Any) -> str:
    """Best-effort extract of the text output from a tool result of any shape."""
    if hasattr(result, "output"):
        return str(result.output or "")
    if isinstance(result, dict):
        return str(result.get("output") or result.get("stdout") or "")
    if isinstance(result, str):
        return result
    return str(result)


def _is_result_envelope(value: Any) -> bool:
    """True when ``value`` carries a textual output (a result envelope)."""
    return hasattr(value, "output") or (
        isinstance(value, dict) and ("output" in value or "stdout" in value)
    )


def _policy_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "on", "1"}:
        return True
    if normalized in {"false", "no", "off", "0"}:
        return False
    return default


def _env_timeout_ms() -> int:
    """Default per-call tool timeout, overridable via NEXUS_TOOL_TIMEOUT_MS."""
    raw = os.environ.get("NEXUS_TOOL_TIMEOUT_MS")
    if raw:
        try:
            value = int(float(raw))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            logger.warning("Invalid NEXUS_TOOL_TIMEOUT_MS=%r; using default", raw)
    return DEFAULT_TOOL_TIMEOUT_MS


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


class _LegacyFunctionTool(BaseTool):
    """Adapt old metadata packages that expose ``execute(params)``.

    These packages are discovered for truthful inventory/diagnostics, but a
    package whose source explicitly reports ``not yet implemented`` is marked
    unavailable by ``ToolEntry`` and never advertised to the model.
    """

    def __init__(self, function: Any, root_dir: str):
        super().__init__(root_dir)
        self._function = function

    async def execute(self, **params):
        result = self._function(dict(params))
        if inspect.isawaitable(result):
            result = await result
        return result


class ToolEntry:
    """Represents a registered tool with its metadata and handler instance."""

    def __init__(self, name: str, schema: dict, instance: Any, check_fn=None, requires_env: Optional[list] = None,
                 unavailable_reason: str = ""):
        self.name = name
        self.schema = schema
        self.instance = instance
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.unavailable_reason = str(unavailable_reason or "")
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
        timeout_ms = self.execution.get(
            "timeout_ms",
            self.execution.get("timeoutMs", schema.get("timeout_ms", _env_timeout_ms())),
        )
        self.timeout_ms = _policy_int(timeout_ms, _env_timeout_ms(), 0)
        self.max_output_chars = _policy_int(
            self.execution.get("max_output_chars", schema.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS)),
            DEFAULT_MAX_OUTPUT_CHARS,
            0,
        )
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
        if self.unavailable_reason:
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
        if self.unavailable_reason:
            missing_env = [var for var in self.requires_env if not os.environ.get(var)]
            if missing_env:
                return {"available": False, "reason": "missing_env", "missing_env": missing_env}
            return {"available": False, "reason": self.unavailable_reason, "missing_env": []}

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

          # ``terminal`` is the only supported command tool. Keep this guard so a
          # stale third-party/configured bash entry cannot reappear at runtime.
    DISABLED_TOOL_NAMES = frozenset({"bash"})

    def __init__(self, root: Optional[str] = None):
        self.root = root or os.getcwd()
        self._tools: Dict[str, ToolEntry] = {}
        self._mcp_clients: List[Any] = []
        self._discover()
        # Skills and MCP tools are extensions of the same model-facing
        # registry.  Discover them here so callers do not need a second,
        # hard-coded registration path.
        self._discover_skills()
        self.init_mcp_tools()

    def close(self) -> None:
        """Stop dynamic MCP children owned by this registry."""
        for client in list(self._mcp_clients):
            try:
                client.stop()
            except Exception:
                logger.debug("MCP client shutdown failed", exc_info=True)
        self._mcp_clients.clear()

    def register_entry(
        self,
        name: str,
        schema: dict,
        instance: Any,
        *,
        requires_env: Optional[list] = None,
        replace: bool = False,
    ) -> ToolEntry:
        """Register a validated runtime tool through the canonical boundary.

        Dynamic discovery uses this method instead of mutating ``_tools`` so
        metadata, execution policy, and availability handling stay identical
        to startup discovery.
        """
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("Tool name is required")
        if not isinstance(schema, dict) or not schema:
            raise ValueError(f"Tool '{normalized_name}' has invalid metadata")
        if instance is None or not callable(getattr(instance, "execute", None)):
            raise ValueError(f"Tool '{normalized_name}' has no executable handler")
        if normalized_name in self._tools and not replace:
            return self._tools[normalized_name]
        entry = ToolEntry(
            name=normalized_name,
            schema=schema,
            instance=instance,
            requires_env=requires_env or [],
        )
        self._tools[normalized_name] = entry
        return entry

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
            if name in self.DISABLED_TOOL_NAMES:
                logger.info("Skipping retired tool: %s", name)
                continue
            tool_dir = os.path.join(tools_dir, name)
            if not os.path.isdir(tool_dir):
                continue
            metadata_path = next(
                (os.path.join(tool_dir, f"{name}{suffix}")
                 for suffix in (".jsnol", ".json")
                 if os.path.isfile(os.path.join(tool_dir, f"{name}{suffix}"))),
                None,
            )
            if not metadata_path:
                continue
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    meta = json.load(f)
                scripts_dir = os.path.join(tool_dir, "scripts")
                handler_cls = None
                legacy_execute = None
                unavailable_reason = ""
                if os.path.isdir(scripts_dir):
                    # Honor .jsnol entry/class so the correct handler is loaded
                    # (scanning for the first BaseTool subclass can pick the wrong
                    # class when a module imports another tool class).
                    entry_rel = meta.get("entry") or ""
                    class_name = meta.get("class")
                    if entry_rel:
                        entry_path = os.path.join(tool_dir, entry_rel)
                    else:
                        # fall back to first .py if entry not declared
                        py = sorted(
                            s for s in os.listdir(scripts_dir)
                            if s.endswith(".py") and not s.startswith("_")
                        )
                        entry_path = os.path.join(scripts_dir, py[0]) if py else None
                    if entry_path and os.path.isfile(entry_path):
                        mod_name = os.path.splitext(os.path.basename(entry_path))[0]
                        try:
                            spec = importlib.util.spec_from_file_location(mod_name, entry_path)
                            if spec and spec.loader:
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                if class_name:
                                    handler_cls = getattr(mod, class_name, None)
                                elif callable(getattr(mod, "execute", None)):
                                    legacy_execute = getattr(mod, "execute")
                                else:
                                    for _, obj in inspect.getmembers(mod, inspect.isclass):
                                        if issubclass(obj, BaseTool) and obj is not BaseTool:
                                            handler_cls = obj
                                            break
                        except Exception:
                            unavailable_reason = "import_failed"
                            logger.warning(f"Could not load: {entry_path}")
                if handler_cls:
                    instance = handler_cls(root_dir=self.root)
                elif legacy_execute:
                    instance = _LegacyFunctionTool(legacy_execute, self.root)
                    try:
                        source = inspect.getsource(legacy_execute).lower()
                        if "not yet implemented" in source:
                            unavailable_reason = "unimplemented"
                    except (OSError, TypeError):
                        pass
                else:
                    instance = None
                    unavailable_reason = unavailable_reason or "no_executable_handler"
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
                    unavailable_reason=unavailable_reason,
                )
                self._tools[name] = entry
                logger.info(f"Registered tool: {name} v{meta.get('version', '?')}")

                # Sync to NATE native tool engine (best-effort)
                self._sync_to_nate(name, meta, instance)
            except Exception as e:
                logger.error(f"Failed to register tool '{name}': {e}")

    def _discover_skills(self) -> int:
        """Register active ``SKILL.md`` records as model-callable tools.

        Skills remain prompt-backed capabilities, but exposing them through
        the same registry lets the model discover them alongside executable
        tools.  The skill registry remains the source of truth for precedence
        and parsing; this method only adapts its records to the tool schema.
        """
        try:
            from skills import NexusSkillMaster
            from tools.nexus_tools.skill_adapter import SkillToolAdapter

            registered = 0
            for skill in NexusSkillMaster(self.root).list_skills():
                if skill.get("active", True) is False:
                    continue
                name = str(skill.get("id") or skill.get("name") or "").strip()
                prompt = str(skill.get("prompt") or "").strip()
                if not name or not prompt or name in self._tools:
                    continue
                schema = {
                    "name": name,
                    "version": skill.get("version", "1.0.0"),
                    "description": skill.get("description") or f"Skill: {name}",
                    "params": {
                        "args": {
                            "type": "string",
                            "description": "Optional task-specific instructions for this skill",
                            "default": "",
                        }
                    },
                    "category": "skill",
                    "source": skill.get("source", "skill"),
                }
                entry = ToolEntry(
                    name=name,
                    schema=schema,
                    instance=SkillToolAdapter(
                        name=name,
                        skill_prompt=prompt,
                        description=schema["description"],
                        root_dir=self.root,
                    ),
                )
                self._tools[name] = entry
                self._sync_to_nate(name, schema, entry.instance)
                registered += 1
            return registered
        except Exception:
            logger.warning("Skill discovery failed", exc_info=True)
            return 0

    def get(self, name: str) -> Optional[ToolEntry]:
        return self._tools.get(name)

    @staticmethod
    def _sync_to_nate(name: str, schema: dict, instance: Any) -> None:
        """Best-effort sync a discovered tool into the NATE native engine."""
        try:
            from intelligence.nate import NATE
            nate = NATE()
            nate.register_tool(
                name=name,
                description=schema.get("description", ""),
                parameters=schema.get("params"),
                required=schema.get("required", []),
                handler=instance.execute if instance else None,
            )
            logger.debug(f"NATE synced tool: {name}")
        except Exception:
            pass  # NATE is optional — don't block tool registration

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
        # Built-in .jsnol metadata commonly marks required fields on each
        # parameter, while MCP exposes the standard JSON Schema shape with a
        # top-level ``required`` array.  Enforce both forms at the single
        # execution boundary so discovered tools have identical semantics.
        required = entry.schema.get("required") or []
        if not isinstance(required, (list, tuple, set)):
            raise ValueError(f"Tool '{entry.name}' has an invalid required schema")
        for param_name in required:
            if str(param_name) not in params:
                raise ValueError(f"Tool '{entry.name}' requires parameter '{param_name}'")
        # Strict schemas may disallow undeclared keys.  ``additionalProperties``
        # can live on the tool schema, inside the ``params`` map, or in the raw
        # MCP ``inputSchema`` — honor all three spellings.  When it is not
        # explicitly ``False``, unknown params remain allowed (backward compat).
        additional_properties: Any = entry.schema.get("additionalProperties")
        if isinstance(entry.schema.get("params"), dict):
            params_level = entry.schema["params"].get("additionalProperties")
            if isinstance(params_level, bool):
                additional_properties = params_level
        if additional_properties is not False:
            input_schema = entry.schema.get("inputSchema")
            if isinstance(input_schema, dict) and input_schema.get("additionalProperties") is False:
                additional_properties = False
        if additional_properties is False:
            declared = set(definitions.keys())
            undeclared = sorted(str(key) for key in params if key not in declared)
            if undeclared:
                raise ValueError(
                    f"Tool '{entry.name}' received undeclared parameter(s): {undeclared} "
                    "(schema sets additionalProperties: false)"
                )
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
            enum_values = definition.get("enum")
            if isinstance(enum_values, (list, tuple, set)) and value not in enum_values:
                raise ValueError(
                    f"Tool '{entry.name}' parameter '{param_name}' must be one of: {list(enum_values)}"
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

    # ── Output Persistence ───────────────────────────────────────────
    # Oversized tool output is persisted to ``context_archive/tool-results/``
    # instead of being silently elided, so downstream consumers always know
    # where the full output lives and only see a small preview envelope.

    def _persist_tool_output(self, entry: ToolEntry, output_text: str, call_id: Optional[str] = None) -> str:
        """Write full tool output to the tool-results archive. Returns the path."""
        archive_dir = os.path.join(self.root, "context_archive", "tool-results")
        os.makedirs(archive_dir, exist_ok=True)
        base = str(call_id) if call_id else f"{entry.name}_{int(time.monotonic() * 1000)}"
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
        path = os.path.join(archive_dir, f"{safe}.txt")
        with open(path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(output_text)
        logger.info("Persisted oversized output for '%s' (%d chars) to %s", entry.name, len(output_text), path)
        return path

    @staticmethod
    def _persist_envelope(path: str, output_text: str) -> str:
        return (
            f"[Persisted to {path}; len={len(output_text)} chars; "
            f"showing first {PERSIST_PREVIEW_CHARS}]\n"
            f"{output_text[:PERSIST_PREVIEW_CHARS]}"
        )

    def _maybe_persist(self, entry: ToolEntry, result: Any, call_id: Optional[str] = None) -> Any:
        """Persist oversized / explicitly-elided tool output to disk.

        Returns the (possibly rewritten) result.  Degrades softly to the legacy
        elision behaviour if the disk write fails.
        """
        max_chars = entry.max_output_chars if entry.max_output_chars > 0 else None
        metadata = getattr(result, "metadata", None)
        elided = isinstance(metadata, dict) and bool(metadata.get("output_truncated"))
        output_text = _result_output_text(result)
        if not elided and (max_chars is None or len(output_text) <= max_chars):
            return result
        if not output_text:
            return result
        if not call_id and hasattr(result, "tool_call_id"):
            call_id = result.tool_call_id or call_id
        try:
            path = self._persist_tool_output(entry, output_text, call_id)
        except Exception:
            logger.warning(
                "Output persistence failed for '%s'; falling back to legacy elision",
                entry.name,
                exc_info=True,
            )
            return result
        envelope = self._persist_envelope(path, output_text)
        if isinstance(result, dict):
            result = dict(result)
            result["output"] = envelope
            result["stdout"] = envelope
            result["metadata"] = {**(result.get("metadata") or {}), "output_persisted": path}
            return result
        if hasattr(result, "output"):
            result.output = envelope
        if hasattr(result, "stdout"):
            result.stdout = envelope
        if isinstance(getattr(result, "metadata", None), dict):
            result.metadata["output_persisted"] = path
        return result

    def _finalize_result(self, entry: ToolEntry, result: Any) -> Any:
        """Post-execution finalization: persist oversized output to disk."""
        if result is None:
            return result
        call_id = getattr(result, "tool_call_id", None) or None
        return self._maybe_persist(entry, result, call_id)

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
                "availability_detail": entry.unavailable_reason,
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
        cancel_token = params.pop("_cancel_token", None)
        self._prepare_execution(entry, params)

        max_retries = _policy_int(entry.execution.get("max_retries", 0), 0, 0)
        retry_delay_ms = _policy_int(entry.execution.get("retry_delay_ms", 1000), 1000, 0)
        attempts = 0

        while True:
            try:
                async with entry._semaphore:
                    if cancel_token and cancel_token.is_cancelled:
                        return ToolCallResult(
                            name=entry.name, status=STATUS_BLOCKED,
                            error_info={"type": "CancelledError", "message": "Tool execution cancelled"},
                            error="Cancelled",
                        )
                    self._bind_runtime_context(entry, runtime_context)
                    await entry.wait_for_cooldown()

                    result = await asyncio.wait_for(
                        entry.instance.execute(**params),
                        timeout=entry.timeout_ms / 1000.0 if entry.timeout_ms > 0 else None,
                    )
                return self._finalize_result(entry, result)
            except asyncio.TimeoutError:
                attempts += 1
                if attempts > max_retries:
                    return ToolCallResult(
                        name=entry.name, status=STATUS_TIMEOUT,
                        error_info={"type": "TimeoutError", "message": f"Timeout after {entry.timeout_ms}ms ({attempts} attempts)", "retryable": True},
                        error=f"Timeout after {entry.timeout_ms}ms",
                    )
                logger.warning("Tool '%s' timed out (attempt %d/%d), retrying in %dms...", entry.name, attempts, max_retries + 1, retry_delay_ms)
                await asyncio.sleep(retry_delay_ms / 1000.0)
                retry_delay_ms = min(retry_delay_ms * 2, 60_000)  # exponential backoff, cap 60s
            except Exception as exc:
                error_cls = classify_error(exc)
                if error_cls["retryable"] and attempts < max_retries:
                    attempts += 1
                    logger.warning("Tool '%s' failed (attempt %d/%d): %s — retrying in %dms...", entry.name, attempts, max_retries + 1, exc, retry_delay_ms)
                    await asyncio.sleep(retry_delay_ms / 1000.0)
                    retry_delay_ms = min(retry_delay_ms * 2, 60_000)
                    continue
                return ToolCallResult(
                    name=entry.name, status=STATUS_ERROR,
                    error_info=error_cls,
                    error=str(exc),
                )


    async def stream_execute(self, name: str, **params) -> AsyncGenerator[Any, None]:
        """Universal streaming adapter for built-in, plugin, skill, and MCP tools.

        Native streaming implementations yield immediately. Legacy atomic tools
        yield their real ToolResult once it exists, without fake delayed chunks.

        Supports retry with exponential backoff (configured via .jsnol execution.max_retries).
        Supports cooperative cancellation via _cancel_token.
        """
        entry = self.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")
        if entry.instance is None:
            raise NotImplementedError(f"Tool '{name}' has no executable handler")
        runtime_context = params.pop("_runtime_context", None)
        cancel_token = params.pop("_cancel_token", None)
        self._prepare_execution(entry, params)

        max_retries = _policy_int(entry.execution.get("max_retries", 0), 0, 0)
        retry_delay_ms = _policy_int(entry.execution.get("retry_delay_ms", 1000), 1000, 0)
        attempts = 0

        while True:
            try:
                async with entry._semaphore:
                    if cancel_token and cancel_token.is_cancelled:
                        yield ToolCallResult(
                            name=entry.name, status=STATUS_BLOCKED,
                            error_info={"type": "CancelledError", "message": "Tool execution cancelled"},
                            error="Cancelled",
                        )
                        return
                    self._bind_runtime_context(entry, runtime_context)
                    await entry.wait_for_cooldown()

                    stream_method = getattr(entry.instance, "stream_execute", None)
                    if callable(stream_method):
                        result = stream_method(**params)
                        if inspect.isasyncgen(result):
                            try:
                                while True:
                                    if cancel_token and cancel_token.is_cancelled:
                                        yield ToolCallResult(name=entry.name, status=STATUS_BLOCKED, error="Cancelled")
                                        return
                                    try:
                                        chunk = await asyncio.wait_for(
                                            result.__anext__(),
                                            timeout=entry.timeout_ms / 1000.0 if entry.timeout_ms > 0 else None,
                                        )
                                    except StopAsyncIteration:
                                        break
                                    yield self._finalize_result(entry, chunk) if _is_result_envelope(chunk) else chunk
                            finally:
                                close = getattr(result, "aclose", None)
                                if callable(close):
                                    await close()
                            return
                        if inspect.isgenerator(result):
                            sentinel = object()
                            while True:
                                if cancel_token and cancel_token.is_cancelled:
                                    yield ToolCallResult(name=entry.name, status=STATUS_BLOCKED, error="Cancelled")
                                    return
                                chunk = await asyncio.to_thread(next, result, sentinel)
                                if chunk is sentinel:
                                    break
                                yield self._finalize_result(entry, chunk) if _is_result_envelope(chunk) else chunk
                            return
                        if inspect.isawaitable(result):
                            yield self._finalize_result(entry, await result)
                            return

                    exec_result = await asyncio.wait_for(
                        entry.instance.execute(**params),
                        timeout=entry.timeout_ms / 1000.0 if entry.timeout_ms > 0 else None,
                    )
                    yield self._finalize_result(entry, exec_result)
                return
            except asyncio.TimeoutError:
                attempts += 1
                if attempts > max_retries:
                    yield ToolCallResult(
                        name=entry.name, status=STATUS_TIMEOUT,
                        error_info={"type": "TimeoutError", "message": f"Timeout after {entry.timeout_ms}ms ({attempts} attempts)", "retryable": True},
                        error=f"Timeout after {entry.timeout_ms}ms",
                    )
                    return
                logger.warning("Tool '%s' stream timed out (attempt %d/%d), retrying in %dms...", entry.name, attempts, max_retries + 1, retry_delay_ms)
                yield ToolCallResult(name=entry.name, status=STATUS_TIMEOUT,
                    error_info={"type": "TimeoutError", "message": f"Attempt {attempts} timed out, retrying...", "retryable": True})
                await asyncio.sleep(retry_delay_ms / 1000.0)
                retry_delay_ms = min(retry_delay_ms * 2, 60_000)
            except Exception as exc:
                error_cls = classify_error(exc)
                if error_cls["retryable"] and attempts < max_retries:
                    attempts += 1
                    logger.warning("Tool '%s' stream failed (attempt %d/%d): %s — retrying in %dms...", entry.name, attempts, max_retries + 1, exc, retry_delay_ms)
                    yield ToolCallResult(name=entry.name, status=STATUS_ERROR,
                        error_info=error_cls)
                    await asyncio.sleep(retry_delay_ms / 1000.0)
                    retry_delay_ms = min(retry_delay_ms * 2, 60_000)
                    continue
                yield ToolCallResult(
                    name=entry.name, status=STATUS_ERROR,
                    error_info=error_cls,
                    error=str(exc),
                )
                return

    # ── Health Checks ───────────────────────────────────────────────────

    async def health_check(self, name: str, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Probe a single tool for liveness.

        Returns a dict with ``healthy`` (bool), ``latency_ms``, and ``error``.
        Tools without health probes default to `healthy=True` (registered + available).
        """
        entry = self.get(name)
        if not entry:
            return {"healthy": False, "latency_ms": 0, "error": "Tool not registered"}
        if not entry.is_available():
            return {"healthy": False, "latency_ms": 0, "error": "Tool unavailable"}

        # If the tool has a health_probe method, use it
        if entry.instance and hasattr(entry.instance, "health_probe"):
            try:
                start = time.monotonic()
                result = await asyncio.wait_for(
                    entry.instance.health_probe(),
                    timeout=timeout_s,
                )
                latency = (time.monotonic() - start) * 1000
                is_healthy = bool(result) if isinstance(result, (bool, int)) else True
                return {
                    "healthy": is_healthy,
                    "latency_ms": round(latency, 2),
                    "error": "" if is_healthy else "Health probe returned falsy",
                }
            except asyncio.TimeoutError:
                return {"healthy": False, "latency_ms": timeout_s * 1000, "error": "Health probe timed out"}
            except Exception as exc:
                return {"healthy": False, "latency_ms": 0, "error": str(exc)[:200]}

        # Default: registered + available = healthy
        return {"healthy": True, "latency_ms": 0, "error": ""}

    async def health_check_all(self, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Run health checks for all registered tools in parallel.

        Returns ``{name: {healthy, latency_ms, error}, ...}`` plus a summary.
        """
        names = list(self._tools.keys())
        if not names:
            return {"tools": {}, "summary": {"total": 0, "healthy": 0, "unhealthy": 0}}

        checks = await asyncio.gather(
            *(self.health_check(name, timeout_s) for name in names),
            return_exceptions=True,
        )
        results = {}
        healthy_count = 0
        for name, check in zip(names, checks):
            if isinstance(check, Exception):
                results[name] = {"healthy": False, "latency_ms": 0, "error": str(check)[:200]}
            else:
                results[name] = check
                if check["healthy"]:
                    healthy_count += 1

        return {
            "tools": results,
            "summary": {
                "total": len(names),
                "healthy": healthy_count,
                "unhealthy": len(names) - healthy_count,
            },
        }

    # ── Execution History ───────────────────────────────────────────────

    def _init_history(self) -> None:
        if not hasattr(self, "_history"):
            self._history: list[Dict[str, Any]] = []
            self._history_limit = max(1, _policy_int(os.environ.get("NEXUS_TOOL_HISTORY_LIMIT", "500"), 500, 1))

    def record_execution(self, name: str, params: Dict[str, Any], result: Any, duration_ms: float, status: str) -> None:
        """Record a structured tool execution entry for audit and analytics."""
        self._init_history()
        entry = {
            "ts": time.time(),
            "name": name,
            "params": {k: (str(v)[:500] if isinstance(v, (str, bytes)) else v) for k, v in (params or {}).items()},
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "output_preview": str(result)[:500] if result is not None else "",
        }
        self._history.append(entry)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]

    def get_history(self, name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent execution history, optionally filtered by tool name."""
        self._init_history()
        if name:
            filtered = [e for e in self._history if e["name"] == name]
            return filtered[-limit:]
        return self._history[-limit:]

    def get_tool_stats(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate execution stats: success rate, avg latency, error breakdown."""
        self._init_history()
        entries = [e for e in self._history if not name or e["name"] == name]
        if not entries:
            return {"total_calls": 0, "success_rate": 0, "avg_latency_ms": 0, "errors": {}}

        total = len(entries)
        success_count = sum(1 for e in entries if e["status"] in (STATUS_OK, "ok"))
        avg_latency = sum(e["duration_ms"] for e in entries) / total if total else 0
        errors: Dict[str, int] = {}
        for e in entries:
            if e["status"] not in (STATUS_OK, "ok"):
                errors[e["status"]] = errors.get(e["status"], 0) + 1

        return {
            "total_calls": total,
            "success_rate": round(success_count / total * 100, 1),
            "avg_latency_ms": round(avg_latency, 2),
            "error_breakdown": errors,
        }

    # ── MCP Auto-Connect ──────────────────────────────────────────────

    def init_mcp_tools(self, config_path: Optional[str] = None) -> int:
        """Connect to configured MCP servers and register their tools.

        Reads ``config/mcp_servers.json`` (or given path), starts each MCP
        server, lists its tools, and registers them via ``MCPToolAdapter``.

        Returns the number of MCP tools registered.
        """
        try:
            mcp_config_path = config_path or os.path.join(self.root, "config", "mcp_servers.json")
            if not os.path.isfile(mcp_config_path):
                return 0
            with open(mcp_config_path, encoding="utf-8") as f:
                servers = json.load(f)
            if isinstance(servers, dict) and isinstance(servers.get("servers"), list):
                # Accept the documented config shape: {"servers": [...]}
                normalized = {}
                for index, item in enumerate(servers["servers"]):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or f"server_{index}")
                    normalized[name] = item
                servers = normalized
            if not isinstance(servers, dict):
                return 0
        except Exception:
            return 0

        from mcp.client import MCPClient

        registered = 0
        for server_name, server_cfg in servers.items():
            if not isinstance(server_cfg, dict):
                continue
            if server_cfg.get("enabled", server_cfg.get("active", True)) is False:
                continue
            command = server_cfg.get("command") or server_cfg.get("cmd")
            args = server_cfg.get("args", [])
            if not command:
                continue
            try:
                client = MCPClient(command, list(args) if isinstance(args, list) else [])
                if not client.start():
                    logger.warning("Failed to start MCP server '%s'", server_name)
                    continue
                self._mcp_clients.append(client)
                requires_env = server_cfg.get("requires_env", [])
                # Wire lifecycle hooks so the registry can park (deregister) a
                # degraded server's tools and re-register them after a lazy
                # reconnect — no phantom calls to a dead transport.
                client.degraded_cb = lambda: self._deregister_mcp_tools(server_name)
                client.recover_cb = lambda tool_defs: self._register_mcp_tools(
                    server_name, client, tool_defs, requires_env=requires_env,
                )
                # Keep tools for healthy / degraded-unprobed servers; drop for
                # confirmed-unavailable ones (server started but never responded).
                # Degrades softly to "assume healthy" when the client predates
                # the tri-state health probe.
                server_health = ""
                health_probe = getattr(client, "health_probe", None)
                if callable(health_probe):
                    try:
                        server_health = health_probe()
                    except Exception:
                        logger.debug("MCP server '%s' health probe raised; assuming healthy", server_name, exc_info=True)
                if server_health == "unavailable":
                    logger.warning("MCP server '%s' is unavailable; skipping its tools", server_name)
                    continue
                tool_defs = client.list_tools() or []
                registered += self._register_mcp_tools(
                    server_name, client, tool_defs, requires_env=requires_env,
                )
            except Exception as exc:
                logger.warning("MCP server '%s' init failed: %s", server_name, exc)
        return registered

    def _register_mcp_tools(self, server_name: str, client: Any, tool_defs: List[Dict[str, Any]],
                            requires_env: Optional[list] = None) -> int:
        """(Re)register the tools belonging to an MCP server into the live registry."""
        from tools.nexus_tools.mcp_adapter import MCPToolAdapter

        registered = 0
        for tool_def in tool_defs or []:
            mcp_name = tool_def.get("name", "")
            if not mcp_name:
                continue
            if mcp_name in self._tools:
                logger.warning(
                    "Skipping MCP tool '%s' from '%s': a local tool already owns that name",
                    mcp_name,
                    server_name,
                )
                continue
            input_schema = tool_def.get("inputSchema") or {}
            properties = input_schema.get("properties") if isinstance(input_schema, dict) else {}
            normalized_schema = {
                **tool_def,
                "name": mcp_name,
                "description": tool_def.get("description", f"MCP tool: {mcp_name}"),
                "params": properties if isinstance(properties, dict) else {},
                "required": input_schema.get("required", []) if isinstance(input_schema, dict) else [],
                "category": "mcp",
                "source": server_name,
            }
            adapter = MCPToolAdapter(mcp_name, client, normalized_schema, root_dir=self.root)
            self.register_entry(
                mcp_name,
                normalized_schema,
                adapter,
                requires_env=list(requires_env or []),
            )
            # Dynamic MCP tools must be visible to the same NATE schema source
            # as built-ins and skills.
            self._sync_to_nate(mcp_name, normalized_schema, adapter)
            registered += 1
            logger.info("MCP tool registered: %s (server: %s)", mcp_name, server_name)
        return registered

    def _deregister_mcp_tools(self, server_name: str) -> List[str]:
        """Park all tools sourced from ``server_name`` so no phantom calls occur.

        Called lazily when the server's transport fails.  Returns the removed names.
        """
        removed = [
            name for name, entry in self._tools.items()
            if entry.schema.get("source") == server_name
        ]
        for name in removed:
            self._tools.pop(name, None)
        if removed:
            logger.warning(
                "Parked %d MCP tool(s) from degraded server '%s': %s",
                len(removed), server_name, removed,
            )
        return removed

    # ── NATE Integration ───────────────────────────────────────────────

    def sync_all_to_nate(self) -> int:
        """Sync all registered tools to the NATE native tool engine.

        Returns the number of tools synced.
        """
        count = 0
        for name, entry in self._tools.items():
            if entry.schema and entry.instance:
                self._sync_to_nate(name, entry.schema, entry.instance)
                count += 1
        return count

    def get_nate_schemas(self, query: str, provider: str = "openai", top_k: int = 5) -> Dict[str, Any]:
        """Retrieve adaptive schemas from NATE for a given query.

        Uses NATE's embedding-based routing to return only the most relevant
        tool schemas, significantly reducing context window usage.
        """
        try:
            from intelligence.nate import NATE
            nate = NATE()
            if not hasattr(nate, "adapter") or len(nate.adapter.all()) == 0:
                self.sync_all_to_nate()
            return nate.get_schemas(query, provider=provider, top_k=top_k)
        except Exception:
            # Fallback: return all tools from registry
            tools = []
            for entry in self._tools.values():
                if entry.is_available() and entry.schema:
                    tools.append({
                        "name": entry.name,
                        "description": entry.schema.get("description", ""),
                        "parameters": entry.schema.get("params", {}),
                    })
            return {"all": tools}



# ── CancellationToken ───────────────────────────────────────────────

class CancellationToken:
    """Lightweight cooperative cancellation token for tool execution chains."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def reset(self) -> None:
        self._cancelled = False

