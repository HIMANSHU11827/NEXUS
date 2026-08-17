"""Real LLM-backed chain-of-thought reasoning tool.

Uses ``reasoning.hyper_engine.HyperReasoningEngine`` with the configured cloud
provider (planner -> critic -> verifier). If no provider/LLM is reachable, it
degrades to the engine's deterministic scaffolding instead of failing.
"""

from __future__ import annotations

__version__ = "3.0.0"

from typing import Any, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult

DEPTH_STEPS = {"simple": 3, "detailed": 5, "deep": 8}


class ReasoningTool(BaseTool):
    name = "reasoning"
    description = (
        "Deep chain-of-thought reasoning: LLM planner + critic + verifier with "
        "problem decomposition, uncertainty estimation, and verification"
    )

    async def execute(
        self,
        problem: str,
        depth: str = "detailed",
        steps: int = 5,
        context: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            from reasoning.hyper_engine import HyperReasoningEngine

            max_steps = min(int(steps or 5), DEPTH_STEPS.get(depth, 5))
            engine, mode, init_err = self._build_engine()

            plan = await engine.aplan(problem, context or "")

            lines = [f"# Reasoning: {problem}", "", f"_Mode: {mode} | depth={depth} | max_steps={max_steps}_", ""]
            if init_err:
                lines.append(f"> LLM unavailable ({init_err}) — deterministic fallback used.")
                lines.append("")

            if plan.rationale:
                lines += ["## Chain of thought", "", plan.rationale, ""]

            lines.append("## Plan")
            lines.append("")
            for i, step in enumerate(plan.steps[:max_steps], 1):
                lines.append(f"### Step {i}: {step.objective}")
                lines.append(f"- tool: `{step.suggested_tool}`  |  risk: **{step.risk}**")
                if step.verifier:
                    lines.append(f"- verify: {step.verifier}")
                lines.append("")

            lines.append("## Critique")
            lines.append("")
            if plan.critiques:
                for c in plan.critiques:
                    lines.append(f"- {c}")
            else:
                lines.append("- No blocking issues identified by the critic.")
            lines.append("")

            lines.append(f"**Uncertainty:** {plan.uncertainty:.2f}")
            lines.append("")

            summary = plan.rationale or "; ".join(s.objective for s in plan.steps[:3])
            verdict = await engine.averify(problem, summary)
            lines.append("## Verification")
            lines.append("")
            lines.append(f"- result: **{'PASS' if verdict.passed else 'FAIL'}** ({verdict.source})")
            if verdict.reason:
                lines.append(f"- reason: {verdict.reason}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                metadata={
                    "mode": mode,
                    "plan_source": plan.source,
                    "uncertainty": plan.uncertainty,
                    "verified": verdict.passed,
                    "steps": len(plan.steps),
                },
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, error=str(e))

    @staticmethod
    def _build_engine():
        """Return (engine, mode, init_error). Never raises."""
        from reasoning.hyper_engine import HyperReasoningEngine

        try:
            from providers.factory import NexusProviderFactory

            provider = NexusProviderFactory().get_provider()
            if provider is not None:
                return HyperReasoningEngine(provider=provider), "llm", None
            return HyperReasoningEngine(enable_llm=False), "deterministic", "no provider configured"
        except Exception as exc:  # noqa: BLE001
            return HyperReasoningEngine(enable_llm=False), "deterministic", str(exc)[:200]
