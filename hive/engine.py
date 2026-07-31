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
import time
import uuid
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

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
    ):
        self.agent_id = agent_id
        self.task = task
        self.persona = persona
        self.parent_run_id = parent_run_id
        self.sink = sink
        self.llm_call = llm_call
        self.root = root or os.getcwd()
        # `tools` is an alias for `tool_registry`; either a ToolRegistry-like
        # object (with async .execute(name, **params)) or a plain callable
        # executor  fn(name, params) -> str | awaitable.
        self.tool_registry = tool_registry if tool_registry is not None else tools
        self.max_steps = max(1, int(max_steps or 1))
        self.transcript: List[Dict[str, str]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.steps_used: int = 0
        self.result: str = ""
        self.status: str = "pending"
        self.started_at: float = 0.0
        self.finished_at: float = 0.0
        self.hive_id: str = ""

    async def _emit(self, event_type: str, status: str, **extra) -> None:
        if not self.sink:
            return
        event: Dict[str, Any] = {
            "event_id": f"sub_{self.agent_id}_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "kind": "subagent",
            "run_id": self.parent_run_id,
            "turn_id": self.parent_run_id,
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

    async def run(self) -> str:
        self.started_at = time.time()
        self.status = "running"
        await self._emit("subagent.started", "running")

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self.task},
        ]

        try:
            if self.tool_registry is not None:
                self.result = await self._run_tool_loop(messages)
            else:
                self.result = await self._llm(messages)

            self.finished_at = time.time()
            duration_ms = int((self.finished_at - self.started_at) * 1000)
            self.status = "success"

            await self._emit(
                "subagent.result", "success",
                payload={"result": self.result[:2000], "full_length": len(self.result)},
                duration_ms=duration_ms,
            )
            await self._emit("subagent.completed", "success", duration_ms=duration_ms)
            return self.result

        except Exception as e:
            self.finished_at = time.time()
            duration_ms = int((self.finished_at - self.started_at) * 1000)
            self.status = "failed"
            err_str = str(e)
            await self._emit(
                "subagent.failed", "failed",
                error={"message": err_str},
                duration_ms=duration_ms,
            )
            raise

        except asyncio.CancelledError:
            self.finished_at = time.time()
            duration_ms = int((self.finished_at - self.started_at) * 1000)
            self.status = "cancelled"
            await self._emit(
                "subagent.failed", "cancelled",
                error={"message": "Sub-agent cancelled"},
                duration_ms=duration_ms,
            )
            raise

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
        if self.tool_registry is None:
            return base
        return (
            base
            + "\n\nYou may call ONE tool per turn using exactly this format:\n"
            '<tool_call>{"tool": "<tool_name>", "params": {...}}</tool_call>\n'
            f"Available tools: {', '.join(self._available_tools()) or 'unknown'}\n"
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

    async def _llm(self, messages: List[Dict[str, str]]) -> str:
        if not self.llm_call:
            return await self._default_llm_call(messages)
        if inspect.iscoroutinefunction(self.llm_call):
            return await self.llm_call(messages)
        result = await asyncio.to_thread(self.llm_call, messages)
        return await result if inspect.isawaitable(result) else result

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

        out = fn()
        if inspect.isawaitable(out):
            out = await out
        # Normalize ToolResult-like objects.
        if hasattr(out, "success") and hasattr(out, "output"):
            text = out.output if out.success else f"ERROR: {getattr(out, 'error', '') or out.output}"
            return str(text)
        return str(out)

    async def _run_tool_loop(self, messages: List[Dict[str, str]]) -> str:
        """Bounded multi-turn loop: LLM -> tool -> observation -> LLM ..."""
        convo = list(messages)
        last_text = ""

        for step in range(self.max_steps):
            self.steps_used = step + 1
            last_text = await self._llm(convo)
            convo.append({"role": "assistant", "content": last_text})
            self.transcript.append({"role": "assistant", "content": last_text})

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
                await self._emit(
                    "subagent.progress", "running",
                    payload={"step": self.steps_used, "tool": name, "params": params},
                )
                try:
                    observation = await self._execute_tool(name, params)
                except Exception as e:  # tool failure must not kill the agent
                    observation = f"TOOL ERROR ({name}): {e}"
                    logger.debug("SubAgent tool error", exc_info=True)

            self.tool_calls.append(
                {"step": self.steps_used, "tool": name, "params": params,
                 "result": str(observation)[:2000], "allowed": safe}
            )
            obs_msg = f"TOOL RESULT ({name}):\n{str(observation)[:4000]}"
            convo.append({"role": "user", "content": obs_msg})
            self.transcript.append({"role": "user", "content": obs_msg})
        else:
            # exhausted steps — ask for a wrap-up without tools
            convo.append({
                "role": "user",
                "content": "Step budget exhausted. Give your FINAL ANSWER now, no tool calls.",
            })
            try:
                last_text = await self._llm(convo)
            except Exception:
                logger.debug("SubAgent wrap-up call failed", exc_info=True)

        return last_text

    async def _default_llm_call(self, messages: List[Dict[str, str]]) -> str:
        try:
            from intelligence.moe_router import NexusMoERouter

            def _router_chat() -> Any:
                # Construction can hit config/disk/network, so keep it off the
                # event loop together with the blocking chat() call.
                router = NexusMoERouter()
                return router, router.chat(messages)

            router, out = await asyncio.to_thread(_router_chat)
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
                out = await asyncio.to_thread(provider.chat, messages)
                if isinstance(out, str) and (
                    out.startswith("Error:") or out.startswith("[PROVIDER_ERROR]")
                ):
                    raise RuntimeError(out)
                return out
            if provider and hasattr(provider, "stream_chat"):
                out = await asyncio.to_thread(
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
    ):
        self.root = root
        self.consolidation_timeout = consolidation_timeout
        self.tool_registry = tool_registry
        self.max_agent_steps = max(1, int(max_agent_steps or 1))
        self._sink: Callable[[Dict[str, Any]], Awaitable[Any] | Any] | None = None
        self._llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None
        self._blackboard: Dict[str, Any] = {}
        self._agents: Dict[str, SubAgent] = {}
        self._hives: Dict[str, List[SubAgent]] = {}
        self._agent_tasks: Dict[str, asyncio.Task[str]] = {}
        self._hive_tasks: Dict[str, asyncio.Task[None]] = {}

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

    def _start_agent(self, agent: SubAgent) -> asyncio.Task[str]:
        return self._track_task(
            self._agent_tasks, agent.agent_id, agent.run()
        )

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
        )
        agent.hive_id = hive_id
        self._agents[agent_id] = agent
        self._hives[hive_id] = [agent]
        self._start_agent(agent)
        return agent

    async def spawn_hive(
        self,
        tasks: List[tuple[str, str]],
        parent_run_id: str = "",
        tool_registry: Any = None,
        max_steps: int | None = None,
    ) -> tuple[str, List[SubAgent]]:
        """Spawn multiple sub-agents concurrently (a "hive").

        Args:
            tasks: List of (task, persona) tuples.
            parent_run_id: Run/turn ID for event linkage.

        Returns:
            (hive_id, list of SubAgent instances).
        """
        if not tasks:
            return "", []

        hive_id = self._make_hive_id()
        agents: List[SubAgent] = []
        for task, persona in tasks:
            agent_id = self._make_agent_id()
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
            )
            agent.hive_id = hive_id
            self._agents[agent_id] = agent
            agents.append(agent)

        self._hives[hive_id] = agents

        agent_tasks = [self._start_agent(agent) for agent in agents]
        self._track_task(
            self._hive_tasks,
            hive_id,
            self._run_hive_tasks(hive_id, agent_tasks),
        )

        return hive_id, agents

    async def _run_hive_tasks(
        self, hive_id: str, tasks: List[asyncio.Task[str]]
    ) -> None:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        agents = self._hives.get(hive_id, [])
        for agent, result in zip(agents, results):
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.warning(f"Hive {hive_id} agent {agent.agent_id} failed: {result}")

    async def cancel_hive(self, hive_id: str) -> None:
        """Cancel and await all work owned by a hive."""
        tasks: List[asyncio.Task[Any]] = []
        hive_task = self._hive_tasks.get(hive_id)
        if hive_task is not None and not hive_task.done():
            hive_task.cancel()
            tasks.append(hive_task)

        for agent in self._hives.get(hive_id, []):
            agent_task = self._agent_tasks.get(agent.agent_id)
            if agent_task is not None and not agent_task.done():
                agent_task.cancel()
                tasks.append(agent_task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def aclose(self) -> None:
        """Cancel and await every outstanding engine-owned task."""
        hive_ids = list(self._hives)
        if hive_ids:
            await asyncio.gather(
                *(self.cancel_hive(hive_id) for hive_id in hive_ids),
                return_exceptions=True,
            )

        remaining = [
            task for task in self._agent_tasks.values() if not task.done()
        ]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

    async def consolidate_hive(
        self,
        hive_id: str,
        timeout: float | None = None,
        llm_call: Callable[[List[Dict[str, str]]], Awaitable[str]] | None = None,
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

        raw = self._concat_results(agents)

        llm_call = llm_call or self._llm_call
        if llm_call is None:
            return raw

        try:
            return await self._llm_consolidate(agents, raw, llm_call)
        except Exception as e:
            logger.warning("Hive %s LLM consolidation failed, using concat: %s", hive_id, e)
            return raw

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
                parts.append(agent.result[:3000])
            elif agent.status != "success":
                parts.append("    (agent failed with no output)")
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
            summary_parts.append(
                f"--- AGENT {i} [{agent.persona}] status={agent.status} ---\n"
                f"TASK: {agent.task}\n"
                f"RESULT:\n{(agent.result or '(no output)')[:3000]}"
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the hive CONSOLIDATOR. Several sub-agents worked in parallel "
                    "on parts of one task. Merge their outputs into ONE coherent answer: "
                    "de-duplicate, resolve contradictions (state them if unresolved), keep "
                    "concrete details (file paths, commands, findings), and note any agent "
                    "that failed. Output the unified answer only — no preamble."
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
        return text or raw

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

    def post_to_blackboard(self, key: str, value: Any) -> None:
        self._blackboard[key] = value

    def get_live_signals(self) -> Dict[str, Any]:
        return dict(self._blackboard)

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
