"""Hive Tool — spawn sub-agents for complex tasks.

Lets the LLM delegate complex work to dedicated sub-agents with
specific personas. Each sub-agent runs as an isolated LLM call
and emits lifecycle events.

Modes:
  • single   — spawn one sub-agent for a single task
  • parallel — spawn multiple sub-agents for independent sub-tasks
  • hive     — spawn a hive of sub-agents and consolidate results

Events:
  subagent.started, subagent.status, subagent.result,
  subagent.failed, subagent.completed
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class HiveTool(BaseTool):
    name = "hive"
    description = "Spawn dedicated sub-agents for complex tasks"

    def __init__(self, root_dir: Optional[str] = None):
        super().__init__(root_dir)
        self._hive = None
        self._runtime_context: Dict[str, Any] = {}

    def set_runtime_context(self, context: Dict[str, Any]) -> None:
        self._runtime_context = dict(context or {})
        sink = self._runtime_context.get("work_event_sink")
        if self._hive is not None:
            self._hive.set_sink(sink)

    def _get_hive(self):
        if self._hive is None:
            from hive.engine import NexusHiveEngine
            registry = self._runtime_context.get("tool_registry")
            if registry is None:
                try:
                    from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
                    registry = ToolRegistry(self.root_dir or os.getcwd())
                except Exception:
                    registry = None
            self._hive = NexusHiveEngine(
                root=self.root_dir or os.getcwd(),
                tool_registry=registry,
            )
        self._hive.set_sink(self._runtime_context.get("work_event_sink"))
        return self._hive

    async def execute(
        self,
        task: str = "",
        persona: str = "WORKER",
        mode: str = "single",
        sub_tasks: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            self.assert_execution_active()
            hive = self._get_hive()
            parent_run_id = str(
                kwargs.get("parent_run_id")
                or kwargs.get("turn_id")
                or self._runtime_context.get("turn_id")
                or self._runtime_context.get("session_id")
                or ""
            )

            if mode == "single":
                agent = await hive.spawn_agent(task=task, persona=persona, parent_run_id=parent_run_id)
                task_fut = hive._agent_tasks.get(agent.agent_id)
                deadline = asyncio.get_running_loop().time() + hive.consolidation_timeout
                try:
                    while agent.status in ("pending", "running"):
                        self.assert_execution_active()
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            await hive.cancel_hive(agent.hive_id)
                            return ToolResult(
                                success=False,
                                error=(
                                    f"Sub-agent {agent.agent_id} timed out after "
                                    f"{hive.consolidation_timeout:g}s"
                                ),
                            )
                        if task_fut is None:
                            await asyncio.sleep(min(0.1, remaining))
                        else:
                            await asyncio.wait({task_fut}, timeout=min(0.1, remaining))
                    self.assert_execution_active()
                except asyncio.CancelledError:
                    await hive.cancel_hive(agent.hive_id)
                    raise
                except RuntimeError:
                    await hive.cancel_hive(agent.hive_id)
                    raise

                if agent.status == "success":
                    return ToolResult(
                        success=True,
                        output=agent.result,
                        metadata={
                            "agent_id": agent.agent_id,
                            "persona": persona,
                            "duration_ms": int((agent.finished_at - agent.started_at) * 1000),
                        },
                    )
                return ToolResult(
                    success=False,
                    error=f"Sub-agent {agent.agent_id} failed",
                )

            elif mode in ("parallel", "hive"):
                tasks_to_spawn = []
                if sub_tasks:
                    for st in sub_tasks:
                        tasks_to_spawn.append((st, persona))
                else:
                    tasks_to_spawn.append((task, persona))

                hive_id, agents = await hive.spawn_hive(tasks_to_spawn, parent_run_id=parent_run_id)
                deadline = asyncio.get_running_loop().time() + hive.consolidation_timeout
                try:
                    while any(agent.status in ("pending", "running") for agent in agents):
                        self.assert_execution_active()
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            await hive.cancel_hive(hive_id)
                            return ToolResult(
                                success=False,
                                error=f"Hive {hive_id} timed out after {hive.consolidation_timeout:g}s",
                            )
                        await asyncio.sleep(min(0.1, remaining))
                    self.assert_execution_active()
                except asyncio.CancelledError:
                    await hive.cancel_hive(hive_id)
                    raise
                except RuntimeError:
                    await hive.cancel_hive(hive_id)
                    raise

                results = []
                successes = 0
                failures = 0
                for agent in agents:
                    if agent.status == "success":
                        results.append(agent.result)
                        successes += 1
                    else:
                        failures += 1

                combined = "\n\n---\n\n".join(
                    f"[{agent.persona}] {agent.task[:80]}\n{agent.result[:1000]}"
                    for agent in agents
                    if agent.result
                )

                return ToolResult(
                    success=failures == 0,
                    output=combined or "No results from sub-agents",
                    metadata={
                        "hive_id": hive_id,
                        "num_agents": len(agents),
                        "successes": successes,
                        "failures": failures,
                    },
                )

            return ToolResult(success=False, error=f"Unknown mode: {mode}")

        except Exception as e:
            logger.warning(f"hive execute failed: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Hive error: {e}")
