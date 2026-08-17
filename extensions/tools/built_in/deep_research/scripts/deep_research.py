"""Deep Research Tool — spawns dedicated research sub-agents.

Decomposes a research query into sub-questions, spawns parallel
sub-agents to investigate each angle, and consolidates findings
into a comprehensive research report.

Events:
  • subagent.started  — research sub-agent begins
  • subagent.status   — progress update from a sub-agent
  • subagent.result   — partial research finding
  • subagent.completed — sub-agent finished
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class DeepResearchTool(BaseTool):
    name = "deep_research"
    description = "Deep research with dedicated sub-agents"

    def __init__(self, root_dir: Optional[str] = None):
        super().__init__(root_dir)
        self._hive = None

    def _get_hive(self):
        if self._hive is None:
            from hive.engine import NexusHiveEngine
            self._hive = NexusHiveEngine(root=self.root_dir or os.getcwd())
        return self._hive

    async def _llm_call(self, messages: List[Dict[str, str]]) -> str:
        try:
            from nexus.capabilities.intelligence.moe_router import NexusMoERouter
            router = NexusMoERouter()
            return router.chat(messages)
        except ImportError:
            logger.warning("tools/deep_research/scripts/deep_research.py:48 suppressed error", exc_info=True)
        try:
            from models.providers.core.factory import NexusProviderFactory
            factory = NexusProviderFactory()
            provider = factory.get_provider_by_name("cloud", "lm_studio")
            if provider:
                if hasattr(provider, "chat"):
                    return provider.chat(messages)
                if hasattr(provider, "stream_chat"):
                    return "".join(list(provider.stream_chat(messages)))
        except Exception as e:
            logger.warning(f"deep_research: llm_call failed: {e}")

        from openai import AsyncOpenAI
        llm_base = os.environ.get("NEXUS_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
        llm_key = os.environ.get("NEXUS_LLM_API_KEY", "not-needed")
        llm_model = os.environ.get("NEXUS_LLM_MODEL", "local-model")
        client = AsyncOpenAI(base_url=llm_base, api_key=llm_key)
        response = await client.chat.completions.create(
            model=llm_model,
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""

    async def _decompose_query(self, query: str, depth: str) -> List[str]:
        num_subqs = {"quick": 2, "deep": 4, "comprehensive": 6}.get(depth, 3)

        decomposition_prompt = (
            f"Break this research query into exactly {num_subqs} specific, "
            f"focused sub-questions that together cover all key aspects:\n\n"
            f"Query: {query}\n\n"
            f"Return only the sub-questions, one per line, starting with '- '"
        )

        messages = [
            {"role": "system", "content": "You are a research strategist. Break down complex topics into focused sub-questions."},
            {"role": "user", "content": decomposition_prompt},
        ]

        result = await self._llm_call(messages)

        sub_questions = []
        for line in result.strip().split("\n"):
            line = line.strip().strip("- *").strip()
            if line and len(line) > 10:
                sub_questions.append(line)

        return sub_questions[:num_subqs] or [query]

    async def execute(
        self,
        query: str,
        depth: str = "deep",
        focus_areas: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        start_time = time.time()
        try:
            sub_questions = await self._decompose_query(query, depth)
            if focus_areas:
                for area in focus_areas:
                    sub_questions.append(f"Focus area: {area}")

            hive = self._get_hive()
            tasks = [(sq, "RESEARCHER") for sq in sub_questions]

            hive_id, agents = await hive.spawn_hive(tasks)

            for agent in agents:
                while agent.status in ("pending", "running"):
                    await asyncio.sleep(0.1)

            report_parts = [
                f"# Deep Research: {query}",
                f"Depth: {depth}",
                f"Sub-questions explored: {len(sub_questions)}",
                f"Total research time: {time.time() - start_time:.1f}s",
                "",
                "---",
                "",
            ]

            for agent in agents:
                status_icon = "✓" if agent.status == "success" else "✗"
                report_parts.append(f"## {status_icon} {agent.persona}: {agent.task[:120]}")
                report_parts.append("")
                if agent.result and agent.status == "success":
                    report_parts.append(agent.result)
                elif agent.status == "failed":
                    report_parts.append("*[Research failed]*")
                report_parts.append("")
                report_parts.append("---")
                report_parts.append("")

            report_parts.append(f"*Generated by NEXUS Deep Research in {time.time() - start_time:.1f}s*")

            report = "\n".join(report_parts)
            metadata = {
                "hive_id": hive_id,
                "sub_questions": sub_questions,
                "num_agents": len(agents),
                "duration_s": round(time.time() - start_time, 1),
            }
            return ToolResult(success=True, output=report, metadata=metadata)

        except Exception as e:
            logger.warning(f"deep_research execute failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Deep research failed: {e}",
                metadata={"query": query, "depth": depth},
            )
