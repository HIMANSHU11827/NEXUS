"""NexusHiveEngine — spawn autonomous sub-agents for deep research and parallel tasks.

Sub-agents run as isolated LLM calls with dedicated persona prompts and
emit `subagent.*` work events that flow through the same pipeline as
the main agent's events (GUI, TUI, SSE, persistence).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


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
    ):
        self.agent_id = agent_id
        self.task = task
        self.persona = persona
        self.parent_run_id = parent_run_id
        self.sink = sink
        self.llm_call = llm_call
        self.root = root or os.getcwd()
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
            {
                "role": "system",
                "content": (
                    f"You are a {self.persona} sub-agent. "
                    f"Complete the following task thoroughly and precisely. "
                    f"Output your reasoning and final answer. "
                    f"Do not ask follow-up questions — just do the work."
                ),
            },
            {"role": "user", "content": self.task},
        ]

        try:
            if self.llm_call:
                if inspect.iscoroutinefunction(self.llm_call):
                    self.result = await self.llm_call(messages)
                else:
                    result = await asyncio.to_thread(self.llm_call, messages)
                    self.result = await result if inspect.isawaitable(result) else result
            else:
                self.result = await self._default_llm_call(messages)

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

    async def _default_llm_call(self, messages: List[Dict[str, str]]) -> str:
        try:
            from intelligence.moe_router import NexusMoERouter
            router = NexusMoERouter()
            return await asyncio.to_thread(router.chat, messages)
        except ImportError:
            logger.warning("hive/engine.py:134 suppressed error", exc_info=True)

        try:
            from providers.factory import NexusProviderFactory
            factory = NexusProviderFactory()
            provider = factory.get_provider_by_name("cloud", "lm_studio")
            if provider and hasattr(provider, "chat"):
                return await asyncio.to_thread(provider.chat, messages)
            if provider and hasattr(provider, "stream_chat"):
                return await asyncio.to_thread(
                    lambda: "".join(provider.stream_chat(messages))
                )
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

    def __init__(self, root: str, consolidation_timeout: float = 30.0):
        self.root = root
        self.consolidation_timeout = consolidation_timeout
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
        )
        agent.hive_id = hive_id
        self._agents[agent_id] = agent
        self._start_agent(agent)
        return agent

    async def spawn_hive(
        self,
        tasks: List[tuple[str, str]],
        parent_run_id: str = "",
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
        self, hive_id: str, timeout: float | None = None
    ) -> str:
        """Wait for a hive within a bounded timeout and consolidate results."""
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

        parts: List[str] = []
        for agent in agents:
            status_icon = "✓" if agent.status == "success" else "✗"
            parts.append(f"[{status_icon}] {agent.persona}: {agent.task[:100]}")
            if agent.result and agent.status == "success":
                parts.append(agent.result[:500])
            parts.append("")

        return "\n".join(parts)

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
