"""NexusHiveEngine — spawn autonomous sub-agents for deep research and parallel tasks.

Sub-agents run as isolated LLM calls with dedicated persona prompts and
emit `subagent.*` work events that flow through the same pipeline as
the main agent's events (GUI, TUI, SSE, persistence).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import threading
import time
import tempfile
import uuid
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

from .effects import HiveEffectLedger
from .state import HiveStateStore
from providers.reliability import redact_secrets

logger = logging.getLogger(__name__)

# Directories sub-agents may never write into (mirrors utils/runtime_guard).
try:  # pragma: no cover - guard is optional at import time
    from utils.runtime_guard import PROTECTED_DIRS as _PROTECTED_DIRS, is_core_path
except Exception:  # pragma: no cover
    _PROTECTED_DIRS = ("orchestrators", "kernel", "nexus", "server")

    def is_core_path(path: Any, protected: Any = _PROTECTED_DIRS) -> bool:  # type: ignore[misc]
        text = str(path or "").replace("\\", "/").lower()
        return any(f"/{d}/" in f"/{text}" for d in protected)


# Tool names / params that indicate a mutating operation.
_WRITE_TOOL_HINTS = ("creating", "modifying", "deleting", "write", "edit", "patch", "remove")
_PATH_KEYS = ("path", "file", "file_path", "target", "filename", "dest", "destination")

_TOOL_CALL_PATTERNS = (
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S | re.I),
    re.compile(r"```(?:tool|tool_call|json)\s*(\{.*?\})\s*```", re.S | re.I),
    re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.S | re.I),
)

_DONE_PATTERNS = (
    re.compile(r"\bFINAL\s*ANSWER\s*:", re.I),
    re.compile(r"<\s*done\s*/?\s*>", re.I),
    re.compile(r"\bTASK\s*COMPLETE\b", re.I),
)


def _safe_text(value: Any, limit: int = 4000) -> str:
    """Bound and redact text before it enters Hive state or model context."""
    return redact_secrets(str(value or ""))[:max(1, int(limit))]


def _safe_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact bounded JSON-like values used by Hive telemetry."""
    if depth > 5:
        return _safe_text(value, 500)
    if isinstance(value, str):
        return _safe_text(value, 4000)
    if isinstance(value, dict):
        return {str(key)[:120]: _safe_value(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:100]]
    if isinstance(value, tuple):
        return [_safe_value(item, depth + 1) for item in value[:100]]
    return value


def parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extract a single structured tool call from LLM text.

    Accepted forms (first match wins)::

        <tool_call>{"tool": "reading", "params": {...}}</tool_call>
        ```tool
        {"tool": "bash", "params": {"command": "ls"}}
        ```

    Returns a dict ``{"tool": str, "params": dict}`` or None.
    """
    if not text:
        return None
    for pattern in _TOOL_CALL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("tool") or data.get("name") or data.get("tool_name")
        if not name:
            continue
        params = data.get("params") or data.get("arguments") or data.get("args") or {}
        if not isinstance(params, dict):
            params = {"input": params}
        return {"tool": str(name), "params": params}
    return None


def is_safe_tool_call(name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
    """Reject sub-agent tool calls that would mutate protected core dirs."""
    lowered = str(name or "").lower()
    mutating = any(hint in lowered for hint in _WRITE_TOOL_HINTS)
    for key, value in (params or {}).items():
        if not isinstance(value, str):
            continue
        if key.lower() in _PATH_KEYS or "/" in value or "\\" in value:
            if is_core_path(value):
                return False, (
                    f"blocked: sub-agents may not touch protected core path '{value}' "
                    f"({', '.join(_PROTECTED_DIRS)})"
                )
    if mutating:
        # Extra scan of raw values for protected dir prefixes.
        blob = " ".join(str(v) for v in (params or {}).values()).replace("\\", "/")
        for d in _PROTECTED_DIRS:
            if re.search(rf"(^|[\s'\"(/]){d}/", blob):
                return False, f"blocked: write into protected core dir '{d}/' is not allowed"
    return True, ""


class _HiveStepBudget:
    """Small event-loop-owned counter shared by all agents in one Hive."""

    def __init__(self, limit: int):
        self.remaining = max(0, int(limit or 0))

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


class SubAgent:
    """A single sub-agent spawned by the Hive engine.

    Each sub-agent runs an isolated LLM call with a persona-tailored
    system prompt and emits lifecycle events into the work event stream.
    """

    def __init__(
        self,
        agent_id: str,
        task: str,
        persona: str,
        parent_run_id: str,
        sink: Callable[[Dict[str, Any]], Awaitable[Any] | Any] | None = None,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None,
        root: str | None = None,
        tool_registry: Any = None,
        tools: Any = None,
        max_steps: int = 6,
        max_retries: int = 2,
        effect_ledger: HiveEffectLedger | None = None,
        effect_reconciler: Callable[[str, str, Dict[str, Any]], Awaitable[Any] | Any] | None = None,
        pause_waiter: Callable[[], Awaitable[None]] | None = None,
        step_budget: Callable[[], bool] | None = None,
        terminal_callback: Callable[[], Any] | None = None,
        # New optional capability metadata (backward-compatible; all optional).
        category: str = "",
        specialization: str = "",
        capabilities: Any = None,
        model: str | None = None,
        provider: str | None = None,
        connection_mode: str = "inherit",
    ):
        self.agent_id = agent_id
        self.task = task
        self.persona = persona
        self.parent_run_id = parent_run_id
        self.sink = sink
        self.llm_call = llm_call
        self.root = root or os.getcwd()
        # Capability metadata (Agent Team / specialization aware).
        self.category = category or ""
        self.specialization = specialization or persona
        self.capabilities = capabilities
        self.model = model
        self.provider = provider
        self.connection_mode = connection_mode
        # `tools` is an alias for `tool_registry`; either a ToolRegistry-like
        # object (with async .execute(name, **params)) or a plain callable
        # executor  fn(name, params) -> str | awaitable.
        self.tool_registry = tool_registry if tool_registry is not None else tools
        self.max_steps = max(1, int(max_steps or 1))
        self.max_retries = max(0, int(max_retries or 0))
        self.effect_ledger = effect_ledger or HiveEffectLedger(self.root)
        # Optional provider/tool-side lookup for effects that may have been
        # committed before the process crashed but were never acknowledged.
        # The callback must return None when the outcome is still unknown.
        self.effect_reconciler = effect_reconciler
        self.pause_waiter = pause_waiter
        self.step_budget = step_budget
        self.terminal_callback = terminal_callback
        self.attempts: int = 0
        self.transcript: List[Dict[str, str]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.steps_used: int = 0
        self.result: str = ""
        self.error: str = ""
        self.status: str = "pending"
        self.started_at: float = 0.0
        self.finished_at: float = 0.0
        self.last_heartbeat: float = time.time()
        self.last_progress_at: float = self.last_heartbeat
        self.replacement_count: int = 0
        self.hive_id: str = ""
        self._lifecycle_generation: int = 0
        self._fenced_through_generation: int = 0
        self._inflight_sync_operations: set[asyncio.Task[Any]] = set()

    def begin_generation(self) -> int:
        """Start a new engine-owned execution generation."""
        self._lifecycle_generation += 1
        return self._lifecycle_generation

    def fence_generation(self, generation: int | None = None) -> int:
        """Prevent an old execution from publishing terminal state."""
        target = self._lifecycle_generation if generation is None else int(generation)
        self._fenced_through_generation = max(
            self._fenced_through_generation, target
        )
        return target

    def generation_is_current(self, generation: int) -> bool:
        return (
            int(generation) == self._lifecycle_generation
            and int(generation) > self._fenced_through_generation
        )

    @property
    def has_inflight_sync_operations(self) -> bool:
        return any(not task.done() for task in self._inflight_sync_operations)

    async def _run_sync_operation(self, fn: Callable[[], Any]) -> Any:
        """Run sync work off-loop while retaining its true completion handle.

        Shielding the worker task means cancellation of the owning agent does
        not make an active worker thread look finished. Recovery can therefore
        quarantine the uncertain operation instead of starting a duplicate.
        """
        task = asyncio.create_task(asyncio.to_thread(fn))
        self._inflight_sync_operations.add(task)

        def _finished(completed: asyncio.Task[Any]) -> None:
            self._inflight_sync_operations.discard(completed)
            if completed.cancelled():
                return
            try:
                completed.exception()
            except asyncio.CancelledError:
                pass

        task.add_done_callback(_finished)
        return await asyncio.shield(task)

    @property
    def checkpoint_path(self) -> str:
        return os.path.join(self.root, ".nexus", "hive", "checkpoints", f"{self.agent_id}.json")

    def checkpoint(self) -> None:
        """Atomically persist the agent's resumable execution snapshot."""
        payload = {
            "version": 1,
            "agent_id": self.agent_id,
            "hive_id": self.hive_id,
            "parent_run_id": self.parent_run_id,
            "task": self.task,
            "persona": self.persona,
            "status": self.status,
            "attempts": self.attempts,
            "steps_used": self.steps_used,
            "max_steps": self.max_steps,
            "max_retries": self.max_retries,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_heartbeat": self.last_heartbeat,
            "last_progress_at": self.last_progress_at,
            "replacement_count": self.replacement_count,
            "transcript": _safe_value(self.transcript[-40:]),
            "tool_calls": _safe_value(self.tool_calls[-40:]),
            "result": _safe_text(self.result, 6000),
            "error": _safe_text(self.error, 2000),
            "updated_at": time.time(),
        }
        directory = os.path.dirname(self.checkpoint_path)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.agent_id}-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.checkpoint_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def restore_checkpoint(self, *, expected_task: str = "", expected_hive_id: str = "") -> bool:
        """Restore transcript/tool history from a matching checkpoint."""
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or str(payload.get("agent_id")) != self.agent_id:
                return False
            if expected_task and str(payload.get("task") or "") != str(expected_task):
                return False
            if expected_hive_id and str(payload.get("hive_id") or "") != str(expected_hive_id):
                return False
            self.hive_id = str(payload.get("hive_id") or self.hive_id)
            self.attempts = int(payload.get("attempts", self.attempts) or self.attempts)
            self.steps_used = int(payload.get("steps_used", self.steps_used) or self.steps_used)
            self.started_at = float(payload.get("started_at", self.started_at) or self.started_at)
            self.finished_at = float(payload.get("finished_at", self.finished_at) or self.finished_at)
            self.last_heartbeat = float(payload.get("last_heartbeat", self.last_heartbeat) or self.last_heartbeat)
            self.last_progress_at = float(payload.get("last_progress_at", self.last_progress_at) or self.last_progress_at)
            self.replacement_count = int(payload.get("replacement_count", self.replacement_count) or self.replacement_count)
            self.transcript = [dict(item) for item in payload.get("transcript", []) if isinstance(item, dict)]
            self.tool_calls = [dict(item) for item in payload.get("tool_calls", []) if isinstance(item, dict)]
            self.result = str(payload.get("result") or self.result)
            self.error = str(payload.get("error") or self.error)
            self.status = str(payload.get("status") or self.status)
            return True

        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            return False

    def _safe_checkpoint(self) -> None:
        try:
            self.checkpoint()
        except Exception as exc:
            logger.debug("SubAgent %s checkpoint failed: %s", self.agent_id, exc)

    def _notify_terminal(self) -> None:
        if not callable(self.terminal_callback):
            return
        try:
            self.terminal_callback()
        except Exception:
            logger.debug(
                "SubAgent %s terminal callback failed", self.agent_id, exc_info=True
            )

    async def _emit(self, event_type: str, status: str, **extra) -> None:
        if not self.sink:
            return
        event: Dict[str, Any] = {
            "event_id": f"sub_{self.agent_id}_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "kind": "subagent",
            "run_id": self.parent_run_id,
            "turn_id": self.parent_run_id,
            "parent_run_id": self.parent_run_id,
            "agent_id": self.agent_id,
            "task_id": self.agent_id,
            "related_subagent": self.agent_id,
            "title": f"{self.persona}: {self.task[:80]}",
            "action": self.persona,
            "target": self.task[:200],
            "status": status,
            "visibility": "public",
            "timestamp": time.time(),
            "hive_id": self.hive_id,
            **extra,
        }
        try:
            result = self.sink(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.debug(f"SubAgent sink failed: {e}")

    def _touch_heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def _touch_progress(self) -> None:
        self.last_progress_at = time.time()
        self.last_heartbeat = self.last_progress_at

    async def _heartbeat_keeper(self, interval: float = 15.0) -> None:
        """Keep the durable heartbeat fresh while the agent is mid-operation.

        ``run()`` can spend minutes inside a single LLM call or tool execution
        without touching any pause boundary; without this keeper the recovery
        sweeper would cancel a healthy agent as "stale" and its uncancellable
        worker thread would duplicate side effects.
        """
        try:
            while True:
                await asyncio.sleep(interval)
                self._touch_heartbeat()
                # Recovery may run in another process, so liveness must be
                # durable rather than only fresh in this engine's memory.
                self._safe_checkpoint()
        except asyncio.CancelledError:
            return

    async def _wait_if_paused(self) -> None:
        """Cooperatively stop at a safe boundary while the Hive is paused."""
        if self.pause_waiter is not None:
            await self.pause_waiter()
        self._touch_progress()

    async def run(self, generation: int | None = None) -> str:
        if generation is None:
            generation = self.begin_generation()
        if not self.generation_is_current(generation):
            raise asyncio.CancelledError("sub-agent generation was fenced")
        self.attempts += 1
        self.started_at = time.time()
        self._touch_progress()
        self.status = "running"
        self._safe_checkpoint()
        await self._emit("subagent.started", "running")
        keeper = asyncio.create_task(self._heartbeat_keeper())

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self.task},
        ]
        if self.transcript:
            messages.extend(self.transcript[-40:])

        try:
            await self._wait_if_paused()
            if self.step_budget is not None and not self.step_budget():
                raise RuntimeError("Hive aggregate step budget exhausted")
            if self.tool_registry is not None:
                candidate_result = await self._run_tool_loop(messages)
            else:
                candidate_result = await self._llm(messages)

            if not str(candidate_result or "").strip():
                raise RuntimeError("sub-agent returned an empty result")

            if not self.generation_is_current(generation):
                raise asyncio.CancelledError("sub-agent generation was fenced")
            self.result = str(candidate_result)
            self.finished_at = time.time()
            duration_ms = int((self.finished_at - self.started_at) * 1000)
            self.status = "success"
            self._safe_checkpoint()
            self._notify_terminal()

            await self._emit(
                "subagent.result", "success",
                payload={"result": _safe_text(self.result, 2000), "full_length": len(self.result)},
                duration_ms=duration_ms,
            )
            await self._emit("subagent.completed", "success", duration_ms=duration_ms)
            return self.result

        except Exception as e:
            if not self.generation_is_current(generation):
                raise asyncio.CancelledError("sub-agent generation was fenced") from None
            self.finished_at = time.time()
            duration_ms = int((self.finished_at - self.started_at) * 1000)
            self.status = "failed"
            err_str = _safe_text(e, 2000)
            self.error = err_str
            self._safe_checkpoint()
            self._notify_terminal()
            await self._emit(
                "subagent.failed", "failed",
                error={"message": err_str},
                duration_ms=duration_ms,
            )
            raise

        except asyncio.CancelledError:
            if self.generation_is_current(generation):
                self.finished_at = time.time()
                duration_ms = int((self.finished_at - self.started_at) * 1000)
                self.status = "cancelled"
                self.error = "Sub-agent cancelled"
                self._safe_checkpoint()
                self._notify_terminal()
                await self._emit(
                    "subagent.failed", "cancelled",
                    error={"message": "Sub-agent cancelled"},
                    duration_ms=duration_ms,
                )
            raise
        finally:
            keeper.cancel()
            done, pending = await asyncio.wait({keeper}, timeout=0.25)
            if done:
                await asyncio.gather(*done, return_exceptions=True)
            if pending:
                logger.warning(
                    "SubAgent %s heartbeat keeper ignored bounded cancellation",
                    self.agent_id,
                )

    # ------------------------------------------------------------------
    # LLM + tool mini-loop
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        base = (
            f"You are a {self.persona} sub-agent. "
            f"Complete the following task thoroughly and precisely. "
            f"Output your reasoning and final answer. "
            f"Do not ask follow-up questions — just do the work."
        )
        # Inject relevant skills into sub-agent context
        skills_context = self._load_relevant_skills()
        if skills_context:
            base += skills_context
        if self.tool_registry is None:
            return base
        header = ""
        if self.specialization and self.specialization != self.persona:
            header += f"\nYour specialization is '{self.specialization}'."
        if self.category:
            header += f"\nYour agent category is '{self.category}'."
        if self.model:
            header += f"\nPreferred model: {self.model}."
        if self.provider:
            header += f"\nPreferred provider/connection: {self.provider}."
        # Surface resolved capability allow-lists so the agent (and the human
        # operator reading the prompt) can see exactly what it may use (§14).
        caps = self.capabilities
        if caps is not None:
            allowed: List[str] = []
            for label, items in (
                ("tools", getattr(caps, "tools", None)),
                ("skills", getattr(caps, "skills", None)),
                ("plugins", getattr(caps, "plugins", None)),
                ("mcp_servers", getattr(caps, "mcp_servers", None)),
            ):
                if items:
                    allowed.append(f"{label}={', '.join(items)}")
            if allowed:
                header += "\nGranted capabilities: " + "; ".join(allowed) + "."
            mode = getattr(caps, "mode", None)
            if mode:
                header += f"\nCapability mode: {mode}."

        return (
            base
            + header
            + "\n\nYou may call ONE tool per turn using exactly this format:\n"
            '<tool_call>{"tool": "<tool_name>", "params": {...}}</tool_call>\n'
            f"Available tools: {', '.join(self._available_tools()) or 'unknown'}\n"
            + f"Tool schemas: {json.dumps(self._available_tool_schemas(), ensure_ascii=False)[:14000]}\n"
            f"You have at most {self.max_steps} tool steps. "
            "When you are finished, reply WITHOUT a tool call and start your "
            "final message with 'FINAL ANSWER:'.\n"
            "HARD RULE: you must never write to, modify, or delete anything under "
            f"{', '.join(f'{d}/' for d in _PROTECTED_DIRS)} — those are protected core dirs."
        )

    def _available_tools(self) -> List[str]:
        reg = self.tool_registry
        try:
            lister = getattr(reg, "list_tools", None)
            if callable(lister):
                listed = lister()
                if isinstance(listed, dict):
                    return sorted(listed.keys())
                if isinstance(listed, (list, tuple)):
                    return [str(x) for x in listed]
            if isinstance(reg, dict):
                return sorted(reg.keys())
        except Exception:
            logger.debug("SubAgent could not enumerate tools", exc_info=True)
        return []

    def _available_tool_schemas(self, limit: int = 80) -> List[Dict[str, Any]]:
        """Expose bounded registry schemas to Hive agents, not names only."""
        reg = self.tool_registry
        if reg is None:
            return []
        schemas: List[Dict[str, Any]] = []
        try:
            names = self._available_tools()
            for name in names[:max(1, int(limit))]:
                entry = reg.get(name) if hasattr(reg, "get") else None
                schema = getattr(entry, "schema", None)
                if not isinstance(schema, dict):
                    continue
                params = schema.get("params") if isinstance(schema.get("params"), dict) else {}
                schemas.append({
                    "name": name,
                    "description": str(schema.get("description") or "")[:180],
                    "parameters": {
                        "type": "object",
                        "properties": {key: {
                            "type": value.get("type", "string") if isinstance(value, dict) else "string",
                            "description": str(value.get("description", ""))[:100] if isinstance(value, dict) else "",
                        } for key, value in params.items()},
                        "required": [key for key in (schema.get("required") or []) if key in params],
                    },
                })
        except Exception:
            logger.debug("SubAgent schema enumeration failed", exc_info=True)
        return schemas

    def _load_relevant_skills(self) -> str:
        """Load skill context relevant to this sub-agent's task and persona.
        
        Maps persona roles to skill categories and injects matching skill prompts
        into the sub-agent's system context. Falls back gracefully if the skills
        engine is unavailable. Never raises.
        """
        try:
            # Persona-to-category mapping
            persona_skill_map = {
                "RESEARCHER": ["research", "search", "web", "analysis"],
                "ENGINEER": ["coding", "tool", "command", "process", "environment"],
                "REVIEWER": ["testing", "error", "validation", "review"],
                "PLANNER": ["planning", "workflow", "architecture"],
                "TESTER": ["testing", "error", "validation", "command"],
                "WORKER": ["tool", "general"],
            }
            relevant = persona_skill_map.get(self.persona.upper(), ["general"])
            try:
                from skills.engine import NexusSkillEngine
                engine = NexusSkillEngine()
            except ImportError:
                from skills import NexusSkillMaster
                engine = NexusSkillMaster(self.root)
            skills = engine.list_skills()
            if not skills:
                return ""
            # Match skills by category overlap with persona
            matching = []
            for skill in skills:
                cat = str(skill.get("category", "")).lower()
                skill_name = str(skill.get("name", "")).lower()
                skill_id = str(skill.get("id", "")).lower()
                combined = f"{cat} {skill_name} {skill_id}"
                if any(r in combined for r in relevant):
                    prompt = skill.get("prompt", "")
                    if prompt:
                        matching.append(f"## Skill: {skill.get('name', skill.get('id', '?'))}\n{prompt[:500]}")
            if matching:
                return "\n\n# RELEVANT SKILLS:\n\n" + "\n\n".join(matching[:3])
            return ""
        except Exception:
            return ""

    async def _llm(self, messages: List[Dict[str, str]]) -> str:
        if not self.llm_call:
            result = await self._default_llm_call(messages)
        elif inspect.iscoroutinefunction(self.llm_call):
            result = await self.llm_call(messages)
        else:
            result = await self._run_sync_operation(
                lambda: self.llm_call(messages)
            )
            if inspect.isawaitable(result):
                result = await result
        self._touch_progress()
        return result

    async def _execute_tool(self, name: str, params: Dict[str, Any]) -> str:
        """Run a tool via a ToolRegistry-like object, dict, or callable executor."""
        reg = self.tool_registry
        fn: Any = None
        if hasattr(reg, "execute"):
            fn = lambda: reg.execute(name, **params)  # noqa: E731
        elif isinstance(reg, dict) and name in reg:
            handler = reg[name]
            fn = lambda: handler(**params)  # noqa: E731
        elif callable(reg):
            fn = lambda: reg(name, params)  # noqa: E731
        else:
            return f"ERROR: no executor available for tool '{name}'"

        # Tool registries often expose synchronous filesystem/process helpers.
        # Calling them inline would block the Hive event loop and prevent
        # pause/cancel signals from reaching sibling workers. Calling the
        # function in a worker also safely handles async callables: they return
        # their coroutine, which is awaited back on the owning loop below.
        out = await self._run_sync_operation(fn)
        if inspect.isawaitable(out):
            out = await out
        self._touch_progress()
        # Normalize ToolResult-like objects.
        if hasattr(out, "success") and hasattr(out, "output"):
            text = out.output if out.success else f"ERROR: {getattr(out, 'error', '') or out.output}"
            return str(text)
        return str(out)

    async def _execute_tool_guarded(self, name: str, params: Dict[str, Any], step: int) -> str:
        key = self.effect_ledger.key(self.agent_id, self.task, step, name, params)
        decision, value = self.effect_ledger.claim(key, self.agent_id, name)
        if decision == "replay":
            return value
        if decision == "uncertain":
            if self.effect_reconciler is not None:
                try:
                    reconciled = self.effect_reconciler(key, name, dict(params))
                    if inspect.isawaitable(reconciled):
                        reconciled = await reconciled
                except Exception as exc:
                    logger.warning(
                        "Effect reconciliation failed for %s/%s: %s",
                        self.agent_id,
                        name,
                        exc,
                    )
                    reconciled = None
                if reconciled is not None:
                    self.effect_ledger.complete(key, reconciled)
                    return str(reconciled)
            return (
                "ERROR: TOOL OUTCOME UNCERTAIN; duplicate execution was refused. "
                "Manual/provider reconciliation is required before retry."
            )
        try:
            result = await self._execute_tool(name, params)
            self.effect_ledger.complete(key, result)
            return result
        except Exception as exc:
            self.effect_ledger.fail(key, _safe_text(exc, 2000))
            raise

    async def _run_tool_loop(self, messages: List[Dict[str, str]]) -> str:
        """Bounded multi-turn loop: LLM -> tool -> observation -> LLM ..."""
        convo = list(messages)
        last_text = ""

        for step in range(self.max_steps):
            await self._wait_if_paused()
            if self.step_budget is not None and not self.step_budget():
                raise RuntimeError("Hive aggregate step budget exhausted")
            self.steps_used = step + 1
            last_text = await self._llm(convo)
            convo.append({"role": "assistant", "content": last_text})
            self.transcript.append({"role": "assistant", "content": last_text})
            self._safe_checkpoint()

            call = parse_tool_call(last_text)
            if not call:
                # No tool call (with or without an explicit FINAL ANSWER marker) = done.
                break

            name, params = call["tool"], call["params"]
            safe, reason = is_safe_tool_call(name, params)
            if not safe:
                observation = f"TOOL DENIED: {reason}"
                logger.warning("SubAgent %s denied tool call %s: %s", self.agent_id, name, reason)
            else:
                await self._wait_if_paused()
                await self._emit(
                    "subagent.progress", "running",
                    payload={"step": self.steps_used, "tool": _safe_text(name, 200), "params": _safe_value(params)},
                )
                try:
                    observation = await self._execute_tool_guarded(name, params, self.steps_used)
                except Exception as e:  # tool failure must not kill the agent
                    observation = f"TOOL ERROR ({name}): {_safe_text(e, 2000)}"
                    logger.debug("SubAgent tool error", exc_info=True)

            self.tool_calls.append(
                {"step": self.steps_used, "tool": name, "params": params,
                 "result": _safe_text(observation, 2000), "allowed": safe}
            )
            obs_msg = f"TOOL RESULT ({_safe_text(name, 200)}):\n{_safe_text(observation, 4000)}"
            convo.append({"role": "user", "content": obs_msg})
            self.transcript.append({"role": "user", "content": obs_msg})
            self._safe_checkpoint()
        else:
            # exhausted steps — ask for a wrap-up without tools
            convo.append({
                "role": "user",
                "content": "Step budget exhausted. Give your FINAL ANSWER now, no tool calls.",
            })
            try:
                if self.step_budget is not None and not self.step_budget():
                    raise RuntimeError("Hive aggregate step budget exhausted")
                last_text = await self._llm(convo)
            except Exception as exc:
                logger.debug("SubAgent wrap-up call failed", exc_info=True)
                raise RuntimeError("sub-agent wrap-up failed") from exc
            if parse_tool_call(last_text):
                raise RuntimeError("sub-agent exhausted tool budget without a final answer")

        return last_text

    async def _default_llm_call(self, messages: List[Dict[str, str]]) -> str:
        try:
            from intelligence.moe_router import NexusMoERouter

            def _router_chat() -> Any:
                # Construction can hit config/disk/network, so keep it off the
                # event loop together with the blocking chat() call.
                router = NexusMoERouter()
                return router, router.chat(messages)

            router, out = await self._run_sync_operation(_router_chat)
            is_err = getattr(router, "_is_provider_error", None)
            if isinstance(out, str) and callable(is_err) and is_err(out):
                raise RuntimeError(out)
            return out
        except (ImportError, RuntimeError):
            logger.warning("hive/engine.py: _default_llm_call router path failed", exc_info=True)

        try:
            from providers.factory import NexusProviderFactory
            factory = NexusProviderFactory()
            provider = factory.get_provider_by_name("cloud", "lm_studio")
            if provider and hasattr(provider, "chat"):
                out = await self._run_sync_operation(
                    lambda: provider.chat(messages)
                )
                if isinstance(out, str) and (
                    out.startswith("Error:") or out.startswith("[PROVIDER_ERROR]")
                ):
                    raise RuntimeError(out)
                return out
            if provider and hasattr(provider, "stream_chat"):
                out = await self._run_sync_operation(
                    lambda: "".join(provider.stream_chat(messages))
                )
                if isinstance(out, str) and (
                    out.startswith("Error:") or out.startswith("[PROVIDER_ERROR]")
                ):
                    raise RuntimeError(out)
                return out
        except Exception as e:
            logger.warning(f"hive/engine.py: default_llm_call failed: {e}")

        raise RuntimeError("No LLM provider available for sub-agent")


class NexusHiveEngine:
    """Orchestrates sub-agent spawning, monitoring, and result consolidation.

    Usage:
        engine = NexusHiveEngine(root="/path/to/project")
        engine.set_sink(loop.work_event_sink)
        results = await engine.spawn_hive([
            ("Research quantum computing", "RESEARCHER"),
            ("Write test cases", "ENGINEER"),
        ])
    """

    def __init__(
        self,
        root: str,
        consolidation_timeout: float = 30.0,
        tool_registry: Any = None,
        max_agent_steps: int = 6,
        max_agent_retries: int = 2,
        max_concurrency: int | None = None,
        max_total_steps: int | None = None,
        max_agent_replacements: int = 2,
        replacement_cancel_timeout: float = 5.0,
        effect_reconciler: Callable[[str, str, Dict[str, Any]], Awaitable[Any] | Any] | None = None,
        shutdown_timeout: float = 5.0,
    ):
        self.root = root
        self.consolidation_timeout = consolidation_timeout
        self.tool_registry = tool_registry
        self.max_agent_steps = max(1, int(max_agent_steps or 1))
        self.max_agent_retries = max(0, int(max_agent_retries or 0))
        # Resource protection: an unattended 24/7 runtime must never let a
        # single hive spawn an unbounded number of parallel sub-agents.
        # ``None`` (the default) now resolves to an env-configurable cap
        # (``NEXUS_HIVE_MAX_CONCURRENCY``, default 8); an explicit ``0`` keeps
        # the documented legacy unlimited behavior.
        if max_concurrency is None:
            try:
                max_concurrency = max(0, int(os.environ.get("NEXUS_HIVE_MAX_CONCURRENCY", "8")))
            except (TypeError, ValueError):
                max_concurrency = 8
        self.max_concurrency = max(0, int(max_concurrency or 0))
        self.max_total_steps = max(0, int(max_total_steps or 0))
        self.max_agent_replacements = max(0, int(max_agent_replacements or 0))
        self.replacement_cancel_timeout = max(0.01, float(replacement_cancel_timeout))
        self.shutdown_timeout = max(0.01, float(shutdown_timeout))
        self.effect_reconciler = effect_reconciler
        self._agent_semaphore = asyncio.Semaphore(self.max_concurrency) if self.max_concurrency else None
        self.effect_ledger = HiveEffectLedger(self.root)
        self.state_store = HiveStateStore(self.root)
        self._sink: Callable[[Dict[str, Any]], Awaitable[Any] | Any] | None = None
        self._llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None
        self._blackboard: Dict[str, Any] = {
            key: item.get("value") for key, item in self.state_store.get_blackboard().items()
        }
        self._blackboard_lock = threading.Lock()
        self._agents: Dict[str, SubAgent] = {}
        self._hives: Dict[str, List[SubAgent]] = {}
        self._agent_tasks: Dict[str, asyncio.Task[str]] = {}
        self._agent_task_generations: Dict[str, int] = {}
        self._hive_tasks: Dict[str, asyncio.Task[None]] = {}
        self._detached_tasks: set[asyncio.Task[Any]] = set()
        self._detached_task_count = 0
        self._closing = False
        self._hive_resume_events: Dict[str, asyncio.Event] = {}
        self._hive_controls: Dict[str, Dict[str, Any]] = {}
        self._hive_consensus: Dict[str, Dict[str, Any]] = {}

    def set_sink(self, sink: Callable[[Dict[str, Any]], Awaitable[Any] | Any] | None) -> None:
        self._sink = sink

    def set_llm_call(self, call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None) -> None:
        self._llm_call = call

    def set_tool_registry(self, registry: Any) -> None:
        """Give spawned sub-agents real tool access (ToolRegistry / dict / callable)."""
        self.tool_registry = registry

    def _make_agent_id(self) -> str:
        return f"agent_{uuid.uuid4().hex[:8]}"

    def _make_hive_id(self) -> str:
        return f"hive_{uuid.uuid4().hex[:8]}"

    async def _emit_hive_event(
        self,
        hive_id: str,
        parent_run_id: str,
        event_type: str,
        status: str,
        **extra,
    ) -> None:
        """Publish a hive-level correlation event through the work event sink."""
        if not self._sink:
            return
        event: Dict[str, Any] = {
            "event_id": f"hive_{hive_id}_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "kind": "handoff" if event_type.startswith("handoff") else "hive",
            "run_id": hive_id,
            "turn_id": hive_id,
            "parent_run_id": parent_run_id or hive_id,
            "hive_id": hive_id,
            "title": event_type,
            "status": status,
            "visibility": "public",
            "timestamp": time.time(),
            **extra,
        }
        try:
            result = self._sink(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.debug("Hive event sink failed for %s: %s", event_type, e)

    @property
    def _hive_control_dir(self) -> str:
        return os.path.join(self.root, ".nexus", "hive", "controls")

    def _hive_control_path(self, hive_id: str) -> str:
        return os.path.join(self._hive_control_dir, f"{hive_id}.json")

    def _persist_hive_control(self, hive_id: str, status: str, reason: str = "") -> None:
        """Atomically persist the operator control state for a Hive."""
        payload = {
            "version": 1,
            "hive_id": hive_id,
            "status": str(status),
            "reason": str(reason or "")[:1000],
            "updated_at": time.time(),
        }
        self._hive_controls[hive_id] = payload
        os.makedirs(self._hive_control_dir, exist_ok=True)
        temporary = f"{self._hive_control_path(hive_id)}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._hive_control_path(hive_id))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def _wait_for_hive_resume(self, hive_id: str, agent: SubAgent) -> None:
        event = self._hive_resume_events.get(hive_id)
        if event is None:
            return
        # Reload the operator control file at every safe boundary. This makes
        # pause/cancel propagation work when another server process wrote the
        # decision, not only when this engine instance received the API call.
        control = self._hive_controls.get(hive_id, {})
        try:
            with open(self._hive_control_path(hive_id), "r", encoding="utf-8") as handle:
                persisted = json.load(handle)
            if isinstance(persisted, dict):
                control = persisted
                self._hive_controls[hive_id] = persisted
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        status = str(control.get("status") or "running").lower()
        if status in {"cancelled", "canceled"}:
            if agent.status not in {"cancelled", "canceled"}:
                agent.status = "cancelled"
                agent._safe_checkpoint()
                await agent._emit(
                    "subagent.cancelled", "cancelled",
                    payload={"reason": control.get("reason", "operator cancellation")},
                )
            raise asyncio.CancelledError(str(control.get("reason") or "operator cancellation"))
        if status == "paused":
            if agent.status == "running":
                agent.status = "paused"
                agent._safe_checkpoint()
                await agent._emit("subagent.paused", "paused", payload={"reason": control.get("reason", "")})
            await event.wait()
            if agent.status == "paused":
                agent.status = "running"
                agent._safe_checkpoint()
                await agent._emit("subagent.resumed", "running")

    async def pause_hive(self, hive_id: str, reason: str = "operator requested pause") -> None:
        """Durably pause a Hive at the next safe model/tool boundary."""
        agents = self._hives.get(hive_id)
        if agents is None:
            raise KeyError(f"Hive not found: {hive_id}")
        event = self._hive_resume_events.setdefault(hive_id, asyncio.Event())
        event.clear()
        self._persist_hive_control(hive_id, "paused", reason)
        for agent in agents:
            if agent.status not in {"success", "failed", "cancelled", "canceled"}:
                agent._safe_checkpoint()

    async def resume_hive(self, hive_id: str) -> None:
        """Resume a paused Hive and persist the running control state."""
        agents = self._hives.get(hive_id)
        if agents is None:
            raise KeyError(f"Hive not found: {hive_id}")
        event = self._hive_resume_events.setdefault(hive_id, asyncio.Event())
        event.set()
        self._persist_hive_control(hive_id, "running")

    async def recover_stuck_agents(
        self,
        stale_after: float = 120.0,
        hive_id: str | None = None,
        max_replacements: int = 1,
    ) -> List[str]:
        """Restart running agents whose durable heartbeat has gone stale.

        The same SubAgent identity is reused so its checkpoint, transcript,
        retry budget, and effect-ledger keys remain authoritative.  The
        replacement starts only after the old asyncio task has been cancelled.
        """
        threshold = max(0.1, float(stale_after))
        allowed = max(0, int(max_replacements))
        if not allowed:
            return []
        now = time.time()
        candidates = [
            agent for agent in self._agents.values()
            if (hive_id is None or agent.hive_id == hive_id)
            and agent.status == "running"
            and now - max(
                float(getattr(agent, "last_heartbeat", 0.0) or 0.0),
                float(getattr(agent, "last_progress_at", 0.0) or 0.0),
            ) >= threshold
        ]
        replaced: List[str] = []
        for agent in candidates[:allowed]:
            if agent.replacement_count >= self.max_agent_replacements:
                agent.status = "failed"
                agent.error = "stale agent replacement budget exhausted"
                agent.finished_at = time.time()
                agent._safe_checkpoint()
                await agent._emit(
                    "subagent.failed", "failed",
                    payload={
                        "quarantined": True,
                        "replacement_count": agent.replacement_count,
                    },
                    error=agent.error,
                )
                continue
            task = self._agent_tasks.get(agent.agent_id)
            generation = self._agent_task_generations.get(
                agent.agent_id, agent._lifecycle_generation
            )
            if task is not None and not task.done():
                agent.fence_generation(generation)
                task.cancel()
                done, pending = await asyncio.wait(
                    {task}, timeout=self.replacement_cancel_timeout
                )
                if done:
                    await asyncio.gather(*done, return_exceptions=True)
                if pending or agent.has_inflight_sync_operations:
                    agent.status = "failed"
                    agent.error = (
                        "stale agent has cancellation-resistant or uncertain work; "
                        "replacement fenced to prevent duplicate effects"
                    )
                    agent.finished_at = time.time()
                    agent._safe_checkpoint()
                    for resistant in pending:
                        self._detach_task(
                            resistant,
                            owner=f"stale-agent:{agent.agent_id}",
                        )
                    await agent._emit(
                        "subagent.failed", "failed",
                        payload={
                            "quarantined": True,
                            "cancellation_timed_out": bool(pending),
                            "uncertain_sync_operation": agent.has_inflight_sync_operations,
                        },
                        error=agent.error,
                    )
                    continue
            agent.replacement_count += 1
            agent.status = "pending"
            agent.finished_at = 0.0
            agent._touch_progress()
            agent._safe_checkpoint()
            await agent._emit(
                "subagent.replaced", "restarting",
                payload={"replacement": agent.replacement_count, "stale_after": threshold},
            )
            self._start_agent(agent)
            replaced.append(agent.agent_id)
        return replaced

    def _track_task(
        self,
        tasks: Dict[str, asyncio.Task[Any]],
        key: str,
        coroutine: Coroutine[Any, Any, Any],
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        tasks[key] = task

        def cleanup(completed: asyncio.Task[Any]) -> None:
            if tasks.get(key) is completed:
                tasks.pop(key, None)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                logger.warning("Hive task %s failed: %s", key, error)

        task.add_done_callback(cleanup)
        return task

    def _detach_task(self, task: asyncio.Task[Any], *, owner: str) -> None:
        """Observe, but never await, work that exceeded a cancellation bound."""
        self._detached_tasks.add(task)
        self._detached_task_count += 1

        def _observe(completed: asyncio.Task[Any]) -> None:
            self._detached_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                logger.warning(
                    "Detached Hive task %s failed after fencing: %s", owner, error
                )
            else:
                logger.info("Detached Hive task %s exited after fencing", owner)

        task.add_done_callback(_observe)

    async def _cancel_tasks_bounded(
        self,
        tasks: List[asyncio.Task[Any]] | set[asyncio.Task[Any]],
        *,
        owner: str,
        timeout: float | None = None,
    ) -> set[asyncio.Task[Any]]:
        active = {task for task in tasks if task is not None and not task.done()}
        for task in active:
            task.cancel()
        if not active:
            return set()
        done, pending = await asyncio.wait(
            active,
            timeout=self.shutdown_timeout if timeout is None else max(0.0, timeout),
        )
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        for task in pending:
            self._detach_task(task, owner=owner)
        if pending:
            logger.warning(
                "Detached %d cancellation-resistant Hive task(s) for %s",
                len(pending),
                owner,
            )
        return pending

    def _start_agent(self, agent: SubAgent) -> asyncio.Task[str]:
        if self._closing:
            raise RuntimeError("Hive engine is closing")
        generation = agent.begin_generation()
        self._agent_task_generations[agent.agent_id] = generation
        return self._track_task(
            self._agent_tasks,
            agent.agent_id,
            self._run_agent_with_retry(agent, generation),
        )

    async def _run_agent_with_retry(
        self, agent: SubAgent, generation: int | None = None
    ) -> str:
        """Retry transient sub-agent failures with bounded backoff.

        The retry is at the agent boundary, so the parent Hive retains one
        stable agent identity and its lifecycle events can be reconciled after
        a process restart. Cancellation is never retried.
        """
        if generation is None:
            generation = agent.begin_generation()

        async def _attempts() -> str:
            attempts = max(0, int(getattr(agent, "max_retries", self.max_agent_retries)))
            for retry_index in range(attempts + 1):
                try:
                    if not agent.generation_is_current(generation):
                        raise asyncio.CancelledError("sub-agent generation was fenced")
                    return await agent.run(generation)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not agent.generation_is_current(generation):
                        raise asyncio.CancelledError("sub-agent generation was fenced") from None
                    if retry_index >= attempts:
                        raise
                    await agent._emit(
                        "subagent.retry", "retrying",
                        payload={
                            "attempt": retry_index + 1,
                            "next_attempt": retry_index + 2,
                            "max_attempts": attempts + 1,
                        },
                        error={"message": str(exc)[:1000]},
                    )
                    await asyncio.sleep(min(2.0, 0.25 * (2 ** retry_index)))
            raise RuntimeError("sub-agent retry loop exhausted")

        try:
            if self._agent_semaphore is None:
                return await _attempts()
            async with self._agent_semaphore:
                return await _attempts()
        finally:
            # ``spawn_agent`` owns a one-agent Hive and has no aggregate
            # _hive_tasks runner to refresh durable control state.  Refresh at
            # the shared agent boundary so success, failure, and cancellation
            # all leave the persisted Hive lifecycle truthful.
            if agent.generation_is_current(generation):
                self._refresh_hive_control(agent.hive_id)

    async def spawn_agent(
        self,
        task: str,
        persona: str = "WORKER",
        parent_run_id: str = "",
        tool_registry: Any = None,
        max_steps: int | None = None,
    ) -> SubAgent:
        """Spawn a single sub-agent for a given task.

        Args:
            task: The task description for the sub-agent.
            persona: Role persona (RESEARCHER, ENGINEER, CRITIC, etc.).
            parent_run_id: Run/turn ID for event linkage.

        Returns:
            The SubAgent instance (already started).
        """
        agent_id = self._make_agent_id()
        hive_id = self._make_hive_id()
        agent = SubAgent(
            agent_id=agent_id,
            task=task,
            persona=persona,
            parent_run_id=parent_run_id or agent_id,
            sink=self._sink,
            llm_call=self._llm_call,
            root=self.root,
            tool_registry=tool_registry if tool_registry is not None else self.tool_registry,
            max_steps=self.max_agent_steps if max_steps is None else max_steps,
            max_retries=self.max_agent_retries,
            effect_ledger=self.effect_ledger,
            effect_reconciler=self.effect_reconciler,
            pause_waiter=lambda: self._wait_for_hive_resume(hive_id, agent),
        )
        agent.hive_id = hive_id
        self._agents[agent_id] = agent
        self._hives[hive_id] = [agent]
        agent.terminal_callback = lambda: self._refresh_hive_control(hive_id)
        self._hive_resume_events[hive_id] = asyncio.Event()
        self._hive_resume_events[hive_id].set()
        self._persist_hive_control(hive_id, "running")
        self._start_agent(agent)
        return agent

    async def spawn_hive(
        self,
        tasks: List[tuple[str, str]],
        parent_run_id: str = "",
        tool_registry: Any = None,
        max_steps: int | None = None,
        dependencies: Optional[Dict[int, List[int]]] = None,
        agent_ids: Optional[List[str]] = None,
        total_step_budget: int | None = None,
        agent_capabilities: Optional[List[Optional[Any]]] = None,
        agent_categories: Optional[List[str]] = None,
        agent_specializations: Optional[List[str]] = None,
    ) -> tuple[str, List[SubAgent]]:
        """Spawn multiple sub-agents concurrently (a "hive").

        Args:
            tasks: List of (task, persona) tuples.
            parent_run_id: Run/turn ID for event linkage.
            agent_capabilities: optional parallel list of resolved
                :class:`CapabilitySpec` (or ``hive.models.CapabilitySpec``)
                instances to attach to each agent, surfacing granted
                capabilities in the agent prompt and for inspection.
            agent_categories: optional parallel list of agent category strings
                (parallel / sequential / specialized / sub_agent / agent_team).
            agent_specializations: optional parallel list of specialization keys.

        Returns:
            (hive_id, list of SubAgent instances).
        """
        if not tasks:
            return "", []

        hive_id = self._make_hive_id()
        agents: List[SubAgent] = []
        allocated_ids: set[str] = set()
        configured_budget = self.max_total_steps if total_step_budget is None else total_step_budget
        step_budget = _HiveStepBudget(configured_budget) if int(configured_budget or 0) > 0 else None
        for index, (task, persona) in enumerate(tasks):
            requested_id = str(agent_ids[index]).strip() if agent_ids and index < len(agent_ids) else ""
            if requested_id and not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", requested_id):
                requested_id = ""
            # Never let a malformed resume manifest or duplicate caller input
            # overwrite the live registry.  Only the first occurrence can
            # hydrate a checkpoint; later collisions receive a fresh identity.
            if requested_id and (requested_id in allocated_ids or requested_id in self._agents):
                requested_id = ""
            agent_id = requested_id or self._make_agent_id()
            while agent_id in allocated_ids or agent_id in self._agents:
                agent_id = self._make_agent_id()
            allocated_ids.add(agent_id)
            agent = SubAgent(
                agent_id=agent_id,
                task=task,
                persona=persona,
                parent_run_id=parent_run_id or hive_id,
                sink=self._sink,
                llm_call=self._llm_call,
                root=self.root,
                tool_registry=(
                    tool_registry if tool_registry is not None else self.tool_registry
                ),
                max_steps=self.max_agent_steps if max_steps is None else max_steps,
                max_retries=self.max_agent_retries,
                effect_ledger=self.effect_ledger,
                effect_reconciler=self.effect_reconciler,
                pause_waiter=None,
                step_budget=step_budget.consume if step_budget is not None else None,
                category=(agent_categories[index] if agent_categories and index < len(agent_categories) else ""),
                specialization=(agent_specializations[index] if agent_specializations and index < len(agent_specializations) else persona),
                capabilities=(agent_capabilities[index] if agent_capabilities and index < len(agent_capabilities) else None),
            )
            agent.hive_id = hive_id
            if requested_id:
                # A resumed checkpoint may belong to the superseded Hive, so
                # validate task identity first, then rebind the live agent to
                # the new Hive identity without trusting checkpoint metadata.
                if agent.restore_checkpoint(expected_task=str(task)):
                    agent.hive_id = hive_id
            self._agents[agent_id] = agent
            agents.append(agent)

        self._hives[hive_id] = agents
        for agent in agents:
            agent.terminal_callback = lambda hive_id=hive_id: self._refresh_hive_control(hive_id)
        self._hive_resume_events[hive_id] = asyncio.Event()
        self._hive_resume_events[hive_id].set()
        for agent in agents:
            agent.pause_waiter = lambda hive_id=hive_id, agent=agent: self._wait_for_hive_resume(hive_id, agent)
        self._persist_hive_control(hive_id, "running")

        if dependencies:
            normalized = {
                int(index): [int(dep) for dep in deps]
                for index, deps in dependencies.items()
                if 0 <= int(index) < len(agents)
            }
            self._track_task(
                self._hive_tasks,
                hive_id,
                self._run_hive_dependency_tasks(hive_id, agents, normalized),
            )
        else:
            agent_tasks = [self._start_agent(agent) for agent in agents]
            self._track_task(
                self._hive_tasks,
                hive_id,
                self._run_hive_tasks(hive_id, agent_tasks),
            )

        return hive_id, agents

    async def _run_hive_dependency_tasks(
        self,
        hive_id: str,
        agents: List[SubAgent],
        dependencies: Dict[int, List[int]],
    ) -> None:
        """Run dependency-ready agents in waves and block failed dependents."""
        pending = set(range(len(agents)))
        completed: Dict[int, bool] = {}
        while pending:
            ready = []
            blocked = []
            for index in sorted(pending):
                deps = [dep for dep in dependencies.get(index, []) if 0 <= dep < len(agents) and dep != index]
                if any(dep in completed and not completed[dep] for dep in deps):
                    blocked.append(index)
                elif all(dep in completed for dep in deps):
                    ready.append(index)
            for index in blocked:
                pending.remove(index)
                completed[index] = False
                agents[index].status = "failed"
                agents[index].result = "dependency failed; agent was not executed"
                agents[index].error = agents[index].result
                agents[index]._safe_checkpoint()
                await agents[index]._emit(
                    "subagent.blocked", "failed",
                    error={"message": agents[index].result},
                )
            if not ready:
                if pending:
                    # Cycles or references to unresolved nodes are a plan
                    # failure, not permission to silently run everything.
                    for index in sorted(pending):
                        pending.remove(index)
                        completed[index] = False
                        agents[index].status = "failed"
                        agents[index].result = "dependency cycle or unresolved prerequisite"
                        agents[index].error = agents[index].result
                        agents[index]._safe_checkpoint()
                        await agents[index]._emit(
                            "subagent.blocked", "failed",
                            error={"message": agents[index].result},
                        )
                continue
            wave = [self._start_agent(agents[index]) for index in ready]
            results = await asyncio.gather(*wave, return_exceptions=True)
            parent_run_id = agents[0].parent_run_id if agents else hive_id
            for index, result in zip(ready, results):
                completed[index] = not isinstance(result, BaseException)
                dependents = sorted(
                    agent_index for agent_index, deps in dependencies.items()
                    if index in deps and 0 <= agent_index < len(agents)
                )
                if dependents:
                    await self._emit_hive_event(
                        hive_id,
                        parent_run_id,
                        "handoff.completed",
                        "success" if completed[index] else "failed",
                        payload={
                            "from": agents[index].agent_id,
                            "to": [agents[agent_index].agent_id for agent_index in dependents],
                            "from_status": agents[index].status,
                        },
                    )
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    logger.warning("Hive %s dependency agent %s failed: %s", hive_id, agents[index].agent_id, _safe_text(result, 1000))
                pending.discard(index)
        self._refresh_hive_control(hive_id)

    def _refresh_hive_control(self, hive_id: str) -> None:
        agents = self._hives.get(hive_id, [])
        statuses = {str(agent.status or "").lower() for agent in agents}
        terminal = {"success", "failed", "cancelled", "canceled", "error"}
        if statuses and statuses.issubset(terminal):
            status = "success" if statuses == {"success"} else (
                "cancelled" if statuses.issubset({"cancelled", "canceled"}) else "failed"
            )
            self._persist_hive_control(hive_id, status)

    async def _run_hive_tasks(
        self, hive_id: str, tasks: List[asyncio.Task[str]]
    ) -> None:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        agents = self._hives.get(hive_id, [])
        for agent, result in zip(agents, results):
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.warning("Hive %s agent %s failed: %s", hive_id, agent.agent_id, _safe_text(result, 1000))
        self._refresh_hive_control(hive_id)

    async def cancel_hive(self, hive_id: str) -> None:
        """Cancel hive work within a hard bound and fence late completion."""
        agents = self._hives.get(hive_id, [])
        terminal = {"success", "failed", "cancelled", "canceled", "error"}
        if agents and all(str(agent.status or "").lower() in terminal for agent in agents):
            self._refresh_hive_control(hive_id)
            return
        # Publish the durable decision before waiting on local tasks. A worker
        # in another server process may be inside a model/tool call and only
        # observe cancellation at its next safe boundary; persisting last
        # leaves that worker running while this method waits indefinitely.
        self._persist_hive_control(hive_id, "cancelled", "operator requested cancellation")
        event = self._hive_resume_events.get(hive_id)
        if event is not None:
            event.set()

        tasks: List[asyncio.Task[Any]] = []
        hive_task = self._hive_tasks.get(hive_id)
        if hive_task is not None and not hive_task.done():
            hive_task.cancel()
            tasks.append(hive_task)

        for agent in agents:
            agent_task = self._agent_tasks.get(agent.agent_id)
            if agent_task is not None and not agent_task.done():
                if str(agent.status or "").lower() in {
                    "success", "failed", "cancelled", "canceled", "error"
                }:
                    # The terminal state is already authoritative. The small
                    # remaining task tail is only event/checkpoint cleanup and
                    # must not be rewritten as cancellation.
                    tasks.append(agent_task)
                    continue
                generation = self._agent_task_generations.get(
                    agent.agent_id, agent._lifecycle_generation
                )
                agent.fence_generation(generation)
                agent.status = "cancelled"
                agent.error = "Hive cancellation fenced late completion"
                agent.finished_at = time.time()
                agent._safe_checkpoint()
                agent_task.cancel()
                tasks.append(agent_task)

        if tasks:
            pending = await self._cancel_tasks_bounded(
                tasks, owner=f"hive-cancel:{hive_id}"
            )
            if pending:
                self._persist_hive_control(
                    hive_id,
                    "cancelled",
                    f"detached {len(pending)} cancellation-resistant local task(s)",
                )

    async def aclose(self) -> None:
        """Fence and boundedly cancel every outstanding engine-owned task."""
        self._closing = True
        hive_ids = list(self._hives)
        if hive_ids:
            await asyncio.gather(
                *(self.cancel_hive(hive_id) for hive_id in hive_ids),
                return_exceptions=True,
            )

        remaining = list({
            task
            for task in [*self._agent_tasks.values(), *self._hive_tasks.values()]
            if not task.done()
        })
        for task in remaining:
            task.cancel()
        if remaining:
            await self._cancel_tasks_bounded(
                remaining, owner="hive-engine-shutdown"
            )

    async def consolidate_hive(
        self,
        hive_id: str,
        timeout: float | None = None,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None,
        *,
        require_quorum: bool = False,
        quorum: int | None = None,
        vote_extractor: Callable[[SubAgent], Any] | None = None,
    ) -> str:
        """Wait for a hive within a bounded timeout and consolidate results.

        When an ``llm_call`` is available (argument or engine-level), all agent
        results are merged by a single LLM call into one unified answer. Falls
        back to deterministic string concatenation otherwise (or on failure).
        """
        agents = self._hives.get(hive_id, [])
        if not agents:
            return f"No hive found: {hive_id}"

        wait_timeout = self.consolidation_timeout if timeout is None else timeout
        if wait_timeout <= 0:
            raise ValueError("consolidation timeout must be greater than zero")

        hive_task = self._hive_tasks.get(hive_id)
        if hive_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(hive_task), wait_timeout)
            except TimeoutError:
                await self.cancel_hive(hive_id)
                raise TimeoutError(
                    f"Hive {hive_id} did not finish within {wait_timeout:g} seconds"
                ) from None
            except asyncio.CancelledError:
                await self.cancel_hive(hive_id)
                raise

        consensus = self.assess_quorum(
            hive_id,
            quorum=quorum,
            vote_extractor=vote_extractor,
        )
        raw = self._concat_results(agents)
        successful_count = sum(
            1 for agent in agents
            if str(agent.status or "").lower() == "success"
            and str(agent.result or "").strip()
        )
        if not successful_count:
            return "HIVE FAILED: no successful agent results available.\n" + raw
        if require_quorum and not consensus["accepted"]:
            return (
                "QUORUM NOT REACHED: "
                f"{consensus['successful']}/{consensus['eligible']} successful agents, "
                f"required {consensus['quorum']}. "
                + "; ".join(consensus["reasons"])
            )

        llm_call = llm_call or self._llm_call
        if llm_call is None:
            return raw

        try:
            return await self._llm_consolidate(agents, raw, llm_call)
        except Exception as e:
            logger.warning("Hive %s LLM consolidation failed, using concat: %s", hive_id, _safe_text(e, 1000))
            return raw

    def assess_quorum(
        self,
        hive_id: str,
        *,
        quorum: int | None = None,
        min_success: int = 1,
        required_personas: List[str] | Tuple[str, ...] = (),
        vote_extractor: Callable[[SubAgent], Any] | None = None,
    ) -> Dict[str, Any]:
        """Return an auditable, deterministic acceptance decision for a Hive.

        Agents may expose an explicit ``VOTE: <label>`` line in their result,
        or callers may supply ``vote_extractor``. Without an explicit vote,
        each normalized result is treated as its own ballot, so contradictory
        free-form answers fail closed instead of being silently accepted.
        """
        agents = self._hives.get(hive_id, [])
        successful = [agent for agent in agents if agent.status == "success" and str(agent.result or "").strip()]
        eligible = len(agents)
        required = max(1, int(min_success or 1))
        target = max(1, int(quorum)) if quorum is not None else max(1, (eligible // 2) + 1)
        reasons: List[str] = []
        if len(successful) < required:
            reasons.append(f"minimum successful agents not met ({len(successful)} < {required})")
        if target > eligible:
            reasons.append(f"quorum exceeds eligible agents ({target} > {eligible})")

        required_set = {str(persona).strip().upper() for persona in required_personas if str(persona).strip()}
        present_set = {str(agent.persona or "").strip().upper() for agent in successful}
        missing_personas = sorted(required_set - present_set)
        if missing_personas:
            reasons.append("missing required personas: " + ", ".join(missing_personas))

        votes: Dict[str, List[str]] = {}
        for agent in successful:
            try:
                raw_vote = vote_extractor(agent) if vote_extractor else self._extract_agent_vote(agent.result)
            except Exception as exc:
                raw_vote = f"__vote_error__:{type(exc).__name__}"
            label = self._normalize_vote(raw_vote)
            votes.setdefault(label, []).append(agent.agent_id)
        winning_vote = ""
        winning_agents: List[str] = []
        if votes:
            winning_vote, winning_agents = max(votes.items(), key=lambda item: (len(item[1]), item[0]))
        if len(winning_agents) < target:
            reasons.append(f"no vote reached quorum ({len(winning_agents)} < {target})")
        accepted = not reasons
        failed = [
            {
                "agent_id": agent.agent_id,
                "persona": agent.persona,
                "status": agent.status,
                "error": _safe_text(getattr(agent, "error", "") or "", 500),
            }
            for agent in agents
            if str(agent.status or "").lower() != "success"
        ]
        assessment = {
            "hive_id": hive_id,
            "accepted": accepted,
            "quorum": target,
            "minimum_success": required,
            "eligible": eligible,
            "successful": len(successful),
            "winning_vote": winning_vote,
            "votes": {key: list(value) for key, value in sorted(votes.items())},
            "missing_personas": missing_personas,
            "failed": failed,
            "reasons": reasons,
            "assessed_at": time.time(),
        }
        self._hive_consensus[hive_id] = assessment
        return assessment

    @staticmethod
    def _normalize_vote(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip().lower())
        return text[:300] or "__no_vote__"

    @staticmethod
    def _extract_agent_vote(result: Any) -> str:
        text = str(result or "")
        match = re.search(r"(?:^|\n)\s*(?:vote|consensus)\s*:\s*([^\n,;]+)", text, re.I)
        if match:
            return match.group(1).strip()
        # Free-form results remain deterministic but normally do not agree
        # unless agents independently produce the same canonical answer.
        return text

    @staticmethod
    def _concat_results(agents: List[SubAgent]) -> str:
        """Deterministic string-concat consolidation (always-available fallback)."""
        parts: List[str] = []
        for agent in agents:
            status_icon = "✓" if agent.status == "success" else "✗"
            parts.append(f"[{status_icon}] {agent.persona}: {agent.task[:100]}")
            # Always surface the result (success OR failure) so failed agents are
            # not silently dropped, and keep a meaningful chunk for the LLM path.
            if agent.result:
                parts.append(_safe_text(agent.result, 3000))
            else:
                parts.append("    (agent produced no output)")
            # Failure reasons must not vanish: surface the recorded error for
            # every non-successful agent, even when it has a partial result.
            error_text = _safe_text(getattr(agent, "error", "") or "", 1000)
            if str(agent.status or "").lower() != "success" and error_text:
                parts.append(f"    (error: {error_text})")
            if getattr(agent, "tool_calls", None):
                used = ", ".join(sorted({c["tool"] for c in agent.tool_calls}))
                parts.append(f"    (tools used: {used})")
            parts.append("")
        return "\n".join(parts)

    async def _llm_consolidate(
        self,
        agents: List[SubAgent],
        raw: str,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]],
    ) -> str:
        summary_parts: List[str] = []
        for i, agent in enumerate(agents, 1):
            status = str(agent.status or "").lower()
            error_text = _safe_text(getattr(agent, "error", "") or "", 1000)
            result_line = _safe_text(agent.result or "(no output)", 3000)
            if status != "success" and error_text:
                result_line += f"\nERROR: {error_text}"
            summary_parts.append(
                f"--- AGENT {i} [{agent.persona}] status={agent.status} ---\n"
                f"TASK: {_safe_text(agent.task, 2000)}\n"
                f"RESULT:\n{result_line}"
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the hive CONSOLIDATOR. Several sub-agents worked in parallel "
                    "on parts of one task. Merge their outputs into ONE coherent answer: "
                    "de-duplicate, resolve contradictions (state them if unresolved), keep "
                    "concrete details (file paths, commands, findings), and note any agent "
                    "that failed. Never invent output for an agent marked failed. "
                    "Output the unified answer only — no preamble."
                ),
            },
            {"role": "user", "content": "\n\n".join(summary_parts)},
        ]

        if inspect.iscoroutinefunction(llm_call):
            out = await llm_call(messages)
        else:
            out = await asyncio.to_thread(llm_call, messages)
            if inspect.isawaitable(out):
                out = await out

        text = str(out or "").strip()
        if not text:
            return raw
        # Verified consolidation: a deterministic footnote guarantees every
        # failed agent stays visible in the final answer, independent of the
        # LLM's compliance with the note-above instruction.
        failed = [
            agent for agent in agents
            if str(agent.status or "").lower() != "success"
        ]
        if failed:
            lines = []
            for agent in failed:
                line = f"- {agent.agent_id} ({agent.persona}): status={agent.status}"
                error_text = _safe_text(getattr(agent, "error", "") or "", 500)
                if error_text:
                    line += f" - {error_text}"
                lines.append(line)
            text += "\n\nFAILED AGENTS (verified, not consolidated):\n" + "\n".join(lines)
        return text

    # ------------------------------------------------------------------
    # Auto-decomposition
    # ------------------------------------------------------------------

    DEFAULT_PERSONAS = ("RESEARCHER", "ENGINEER", "REVIEWER", "PLANNER", "TESTER")

    async def decompose_task(
        self,
        task: str,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None,
        max_subtasks: int = 4,
    ) -> List[Tuple[str, str]]:
        """Split a complex task into ``[(subtask, persona), ...]``.

        Uses an LLM when one is available (JSON output), otherwise falls back
        to a deterministic heuristic split.
        """
        task = str(task or "").strip()
        if not task:
            return []

        max_subtasks = max(1, min(int(max_subtasks or 1), 8))
        llm_call = llm_call or self._llm_call
        if llm_call is not None:
            try:
                parsed = await self._llm_decompose(task, llm_call, max_subtasks)
                if parsed:
                    return parsed[:max_subtasks]
            except Exception as e:
                logger.warning("Hive decompose_task LLM failed, using fallback: %s", e)

        return self._heuristic_decompose(task, max_subtasks)

    async def _llm_decompose(
        self,
        task: str,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]],
        max_subtasks: int,
    ) -> List[Tuple[str, str]]:
        personas = ", ".join(self.list_personas().keys())
        messages = [
            {
                "role": "system",
                "content": (
                    f"Split the user's task into at most {max_subtasks} INDEPENDENT, "
                    "parallelizable subtasks. Each subtask must be self-contained. "
                    f"Assign each one a persona from: {personas}.\n"
                    'Reply with JSON ONLY: {"subtasks": [{"task": "...", "persona": "..."}]}'
                ),
            },
            {"role": "user", "content": task},
        ]

        if inspect.iscoroutinefunction(llm_call):
            out = await llm_call(messages)
        else:
            out = await asyncio.to_thread(llm_call, messages)
            if inspect.isawaitable(out):
                out = await out

        text = str(out or "")
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return []
        data = json.loads(match.group(0))
        items = data.get("subtasks") or data.get("tasks") or []
        valid = set(self.list_personas().keys())
        result: List[Tuple[str, str]] = []
        for item in items:
            if isinstance(item, str):
                result.append((item.strip(), "WORKER"))
                continue
            if not isinstance(item, dict):
                continue
            sub = str(item.get("task") or item.get("subtask") or "").strip()
            if not sub:
                continue
            persona = str(item.get("persona") or "WORKER").strip().upper()
            result.append((sub, persona if persona in valid else "WORKER"))
        return result

    def _heuristic_decompose(self, task: str, max_subtasks: int) -> List[Tuple[str, str]]:
            """Deterministic fallback: numbered/bulleted lines, comma/clause split, else sentence split."""
            lines = [ln.strip() for ln in task.splitlines() if ln.strip()]
            items = [
                re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", ln)
                for ln in lines
                if re.match(r"^\s*(?:\d+[.)]|[-*•])\s+", ln)
            ]
            if not items:
                # split on sentence boundaries first
                items = [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", task) if s.strip()]
            if len(items) <= 1:
                # split on coordinating conjunctions / commas into parallel clauses
                parts = re.split(r",\s+(?:and\s+)?|(?:\s+and\s+)", task)
                items = [p.strip().strip(",. ") for p in parts if p.strip()]
            if len(items) <= 1:
                items = [task]

            items = [i for i in items if i][:max_subtasks]
            personas = self.DEFAULT_PERSONAS
            return [(item, personas[i % len(personas)]) for i, item in enumerate(items)]

    def post_to_blackboard(
        self,
        key: str,
        value: Any,
        *,
        expected_version: int | None = None,
        writer: str = "",
    ) -> Dict[str, Any]:
        """Persist a shared signal with optimistic conflict detection."""
        record = self.state_store.put_blackboard(
            key, value, expected_version=expected_version, writer=writer,
        )
        with self._blackboard_lock:
            self._blackboard[str(key)] = value
        return record

    def get_live_signals(self) -> Dict[str, Any]:
        durable = self.state_store.get_blackboard()
        with self._blackboard_lock:
            self._blackboard = {key: item.get("value") for key, item in durable.items()}
            return dict(self._blackboard)

    def get_blackboard_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Return values plus versions for conflict-safe agent handoffs."""
        return self.state_store.get_blackboard()

    def register_artifact(
        self,
        path: str,
        *,
        artifact_id: str = "",
        hive_id: str = "",
        agent_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return self.state_store.register_artifact(
            path,
            artifact_id=artifact_id,
            hive_id=hive_id,
            agent_id=agent_id,
            metadata=metadata,
        )

    def reconcile_artifacts(self, hive_id: str = "") -> List[Dict[str, Any]]:
        return self.state_store.reconcile_artifacts(hive_id)

    def get_agent(self, agent_id: str) -> Optional[SubAgent]:
        return self._agents.get(agent_id)

    def list_agents(self, status: str = "") -> List[SubAgent]:
        if status:
            return [a for a in self._agents.values() if a.status == status]
        return list(self._agents.values())

    def list_personas(self) -> Dict[str, str]:
        return {
            "RESEARCHER": "Researches sources, facts, context, and alternatives.",
            "ENGINEER": "Implements code changes and technical fixes.",
            "REVIEWER": "Reviews risks, bugs, tests, and regressions.",
            "PLANNER": "Breaks larger goals into ordered execution steps.",
            "TESTER": "Runs validation, reproductions, and quality checks.",
        }

    @staticmethod
    def extract_changed_files(content: str) -> list[str]:
        """Best-effort parser for file paths mentioned in Hive artifacts."""
        import re
        text = str(content or "")
        found: list[str] = []
        seen: set[str] = set()

        patterns = [
            r"(?im)^changed_files:\s*(.+)$",
            r"(?im)^files?(?:\s+touched|\s+changed)?\s*:\s*(.+)$",
            r"(?im)^(?:path|file)\s*:\s*([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)\s*$",
            r"(?im)^(?:\+\+\+\s+b/|---\s+a/)([A-Za-z0-9_./\\-]+)$",
            r"`([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)`",
        ]

        def add_candidate(raw: str) -> None:
            value = raw.strip().strip("`'\"")
            if not value or value.lower() in {"none", "n/a", "null"}:
                return
            if "." not in value or value.endswith(":"):
                return
            normalized = value.replace("\\", "/")
            if normalized not in seen:
                seen.add(normalized)
                found.append(normalized)

        for pattern in patterns:
            for match in re.findall(pattern, text):
                if isinstance(match, tuple):
                    for part in match:
                        add_candidate(part)
                elif "," in match:
                    for part in match.split(","):
                        add_candidate(part)
                else:
                    add_candidate(match)

        return found

    def __repr__(self) -> str:
        return f"<NexusHiveEngine agents={len(self._agents)} hives={len(self._hives)}>"
