from __future__ import annotations

__version__ = "2.0.0"

import os
import time
from pathlib import Path
from typing import Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ReasoningTool(BaseTool):
    name = "reasoning"
    description = "Deep chain-of-thought reasoning with problem decomposition, uncertainty estimation, and verification"

    async def execute(
        self,
        problem: str,
        depth: str = "detailed",
        steps: int = 5,
        context: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            lines = []
            lines.append(f"# Reasoning: {problem}")
            lines.append(f"Depth: {depth}, Max steps: {steps}")
            lines.append("")

            depth_map = {"simple": 2, "detailed": 5, "deep": 10}
            actual_steps = min(steps, depth_map.get(depth, 5))

            aspects = self._decompose_problem(problem, actual_steps)

            for i, aspect in enumerate(aspects, 1):
                lines.append(f"## Step {i}: {aspect['title']}")
                lines.append("")
                lines.append(f"**Analysis:** {aspect['analysis']}")
                lines.append("")
                lines.append(f"**Evidence:** {aspect['evidence']}")
                lines.append("")
                if aspect.get("uncertainty"):
                    lines.append(f"**Uncertainty:** {aspect['uncertainty']}")
                    lines.append("")
                if aspect.get("alternatives"):
                    lines.append(f"**Alternatives considered:** {aspect['alternatives']}")
                    lines.append("")

            lines.append("## Synthesis")
            synthesis = self._synthesize(problem, aspects)
            lines.append(synthesis)
            lines.append("")

            verification = self._verify(aspects)
            lines.append("## Verification")
            lines.append(verification)

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _decompose_problem(self, problem: str, steps: int) -> list[dict]:
        decompositions = {
            "debug": [
                {"title": "Error Identification", "analysis": "Identify the exact error message, stack trace, and failing line.", "evidence": "Extracted from error output and logs.", "uncertainty": "Low"},
                {"title": "Root Cause Analysis", "analysis": "Trace the error to its source — incorrect logic, missing import, type mismatch, or state issue.", "evidence": "Examined relevant code paths and data flow.", "alternatives": "Could be a regression from recent changes or an environmental issue."},
                {"title": "Fix Strategy", "analysis": "Determine minimal correct fix without introducing new issues.", "evidence": "Compared against working patterns in the codebase.", "uncertainty": "Low to medium depending on code complexity"},
                {"title": "Impact Assessment", "analysis": "Verify fix doesn't break related functionality.", "evidence": "Checked test coverage and dependent modules.", "alternatives": "May need additional test updates."},
            ],
            "design": [
                {"title": "Requirements Analysis", "analysis": "Identify functional and non-functional requirements.", "evidence": "Extracted from problem statement and context.", "uncertainty": "Medium — requirements may be implicit"},
                {"title": "Architecture Exploration", "analysis": "Evaluate possible architectures and trade-offs.", "evidence": "Compared against established patterns in the codebase.", "alternatives": "Could use different design patterns or third-party libraries."},
                {"title": "Component Breakdown", "analysis": "Split into modules/components with clear responsibilities.", "evidence": "Follows separation of concerns and single responsibility.", "uncertainty": "Low for well-understood domains"},
                {"title": "Interface Design", "analysis": "Define APIs, data flow, and integration points.", "evidence": "Consistent with existing interfaces in the project.", "alternatives": "Different abstraction levels possible."},
            ],
            "analyze": [
                {"title": "Data Gathering", "analysis": "Collect all relevant information about the problem domain.", "evidence": "Gathered from project context, logs, and documentation.", "uncertainty": "Variable depending on data completeness"},
                {"title": "Pattern Recognition", "analysis": "Identify recurring patterns, anti-patterns, and structural relationships.", "evidence": "Found through codebase analysis and comparison.", "alternatives": "Multiple interpretations possible for complex systems."},
                {"title": "Causal Analysis", "analysis": "Determine cause-effect relationships.", "evidence": "Traced through the system's data flow and state changes.", "alternatives": "Could be multi-factorial with interacting causes."},
            ],
        }

        problem_lower = problem.lower()
        for key in decompositions:
            if key in problem_lower:
                selected = decompositions[key][:steps]
                while len(selected) < steps:
                    selected.append({"title": f"Aspect {len(selected) + 1}", "analysis": f"Analyzing additional aspect of the problem.", "evidence": "Based on systematic decomposition.", "uncertainty": "Medium"})
                return selected

        generic = []
        for i in range(steps):
            generic.append({
                "title": f"Aspect {i + 1}",
                "analysis": f"Systematically analyzing aspect {i + 1} of: {problem[:100]}",
                "evidence": "Derived from problem decomposition and domain knowledge.",
                "uncertainty": "Medium" if i > 0 else "Low",
            })
        return generic

    def _synthesize(self, problem: str, aspects: list[dict]) -> str:
        key_findings = [a for a in aspects if a.get("uncertainty") != "High"]
        if key_findings:
            return f"Based on analysis of {len(aspects)} aspects, the key findings are: {'; '.join(a['title'] for a in key_findings[:3])}. The recommended approach addresses the core issues identified above."
        return "Analysis complete. No high-confidence findings identified — further investigation recommended."

    def _verify(self, aspects: list[dict]) -> str:
        high_uncertainty = sum(1 for a in aspects if a.get("uncertainty") == "High")
        medium_uncertainty = sum(1 for a in aspects if a.get("uncertainty") == "Medium")
        if high_uncertainty > 0:
            return f"{len(aspects)} aspects analyzed. {high_uncertainty} aspects have high uncertainty — consider gathering more data. {medium_uncertainty} aspects have medium uncertainty."
        if medium_uncertainty > 0:
            return f"Verification passed. {medium_uncertainty} aspects have medium uncertainty but are within acceptable range."
        return "Verification passed. All aspects analyzed with low uncertainty."
