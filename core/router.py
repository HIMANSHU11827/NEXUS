"""
NEXUS NEXT-GEN INTENT ROUTER — Smart multi-level intent classification.
No keyword guessing. Uses scoring, context awareness, and task decomposition.
"""

import re
from typing import Dict, List, Any, Tuple, Optional


class IntentResult:
    """Structured intent classification result."""

    intent: str
    confidence: float
    needs_tools: bool
    tool_hints: List[str]
    complexity: str

    def __init__(
        self,
        intent: str,
        confidence: float,
        needs_tools: bool = False,
        tool_hints: Optional[List[str]] = None,
        complexity: str = "simple",
    ) -> None:
        self.intent = intent
        self.confidence = confidence
        self.needs_tools = needs_tools
        self.tool_hints = tool_hints or []
        self.complexity = complexity

    @property
    def task_type(self) -> str:
        """Alias for intent to support legacy modules."""
        return self.intent

    def __repr__(self) -> str:
        return f"Intent({self.intent}, conf={self.confidence:.0%}, tools={self.needs_tools}, hints={self.tool_hints})"


class IntentRouter:
    """
    Next-gen intent router with multi-signal classification.

    Scoring system:
    - Each pattern adds points to intent categories
    - Highest score wins (with confidence based on margin)
    - Tool hints guide downstream tool selection
    - Neural fallback for ambiguous queries
    """

    def __init__(self, router=None):
        from core.cognition.intent_engine import IntentEngine
        self.neural_engine = IntentEngine(router)

    SIGNALS: Dict[str, Dict[str, Any]] = {
        "code": {
            "patterns": [
                r"\b(write|create|implement|build|add|fix|refactor|code|function|class|module)\b",
                r"\b(bug|error|exception|traceback|crash|broken)\b",
                r"\b(\.py|\.js|\.ts|\.java|\.go|\.rs|\.cpp)\b",
                r"```",
            ],
            "weight": 1.5,
            "tools": ["file_read", "file_edit", "bash", "grep", "glob"],
        },
        "file_ops": {
            "patterns": [
                r"\b(read|write|edit|create|delete|move|copy|list|find|search)\b.*\b(file|files|dir|directory|folder|path)\b",
                r"\b(cat|ls|cd|mkdir|rm|cp|mv|touch)\b",
                r"\b(glob|grep|find_in|search_in)\b",
            ],
            "weight": 1.3,
            "tools": ["file_read", "file_edit", "glob", "grep", "bash"],
        },
        "research": {
            "patterns": [
                r"\b(search|find|look up|google|research|what is|how to|explain|tell me about)\b",
                r"\b(url|website|web|http|www\.|\.com|\.org|\.io)\b",
                r"\b(fetch|scrape|read_url|browse)\b",
            ],
            "weight": 1.2,
            "tools": ["web_search", "web_fetch", "grep"],
        },
        "debug": {
            "patterns": [
                r"\b(debug|diagnose|why|what's wrong|not working|failing|test|check|verify)\b",
                r"\b(log|stack|trace|inspect|analyze)\b",
            ],
            "weight": 1.4,
            "tools": ["bash", "grep", "file_read", "lsp", "test"],
        },
        "git": {
            "patterns": [
                r"\b(git|commit|push|pull|branch|merge|diff|status|log|checkout)\b",
                r"\b(PR|pull request|merge request)\b",
            ],
            "weight": 1.3,
            "tools": ["git", "bash"],
        },
        "test": {
            "patterns": [
                r"\b(run tests?|pytest|unittest|test suite|coverage|lint|format)\b",
                r"\b(test_.+|_test\.|spec\.)\b",
            ],
            "weight": 1.5,
            "tools": ["test", "bash"],
        },
        "hive": {
            "patterns": [
                r"\b(swarm|hive|colony|delegate|parallel|sub-agent|spawn|multi-agent)\b",
                r"\b(many brains|distribute|massive task|split work)\b",
            ],
            "weight": 2.0,
            "tools": ["swarm_hive", "hive_report"],
        },
    }

    def discover_intent(self, text: str) -> str:
        """Legacy compatibility - returns 'agentic' or 'chat'."""
        result = self.classify(text)
        return "agentic" if result.needs_tools else "chat"

    def classify(
        self, text: str, context: Optional[Dict[str, Any]] = None
    ) -> IntentResult:
        """
        Multi-signal intent classification with confidence scoring.
        Returns structured IntentResult with tool hints.
        """
        text_lower = text.lower().strip()

        scores: Dict[str, float] = {}
        for intent_name, signal in self.SIGNALS.items():
            score = 0.0
            for pattern in signal["patterns"]:
                matches = len(re.findall(pattern, text_lower))
                score += matches * signal["weight"]
            if score > 0:
                scores[intent_name] = score

        complexity = self._detect_complexity(text_lower, scores)

        total_score = sum(scores.values())
        needs_tools = total_score >= 1.5

        if len(text_lower) < 30 and total_score < 3.0:
            needs_tools = False

        # ⚡ 3.9: Skill-Deep Mapping (Prioritize Learned Logic)
        from core.skills import NexusSkillMaster
        from core.nexus_path import _ROOT
        skills = NexusSkillMaster(_ROOT).list_skills()
        for s in skills:
            if s["id"].lower() in text_lower:
                return IntentResult(
                    intent=f"SKILL:{s['id']}",
                    confidence=0.98,
                    needs_tools=True,
                    tool_hints=["use_skill"],
                    complexity="medium"
                )

        if scores:
            best_intent = max(scores, key=scores.get)
            best_score = scores[best_intent]
            second_score = (
                sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
            )
            confidence = min(
                0.95, 0.5 + (best_score - second_score) / (total_score + 1)
            )
        else:
            # 🧠 [NEURAL_FALLBACK]: Ask the brain if heuristics fail
            neural_intent = self.neural_engine.classify(text_lower)
            if neural_intent != "unknown":
                best_intent = neural_intent.value
                confidence = 0.85
                needs_tools = neural_intent not in ["social", "unknown"]
            else:
                best_intent = "chat"
                confidence = 0.9
                needs_tools = False

        tool_hints = (
            self.SIGNALS.get(best_intent, {}).get("tools", []) if needs_tools else []
        )

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            needs_tools=needs_tools,
            tool_hints=tool_hints,
            complexity=complexity,
        )

    def _detect_complexity(self, text: str, scores: Dict[str, float]) -> str:
        """Detect task complexity from signals."""
        active_intents = len([s for s in scores.values() if s >= 1.0])
        if active_intents >= 3:
            return "complex"
        elif active_intents >= 2:
            return "medium"

        if len(text) > 300:
            return "complex"
        elif len(text) > 150:
            return "medium"

        conjunctions = len(
            re.findall(r"\b(and then|after that|also|then|finally|next)\b", text)
        )
        if conjunctions >= 2:
            return "complex"
        elif conjunctions >= 1:
            return "medium"

        return "simple"

    def decompose(self, text: str) -> List[Dict[str, Any]]:
        """
        Decompose multi-intent queries into sub-tasks.
        "Search for React docs and then create a component" -> 2 sub-tasks
        """
        parts = re.split(
            r"\b(and then|then after that|after that|finally|also then|; then)\b", text
        )
        subtasks: List[Dict[str, Any]] = []
        for part in parts:
            part = part.strip()
            if len(part) < 10:
                continue
            result = self.classify(part)
            if result.intent != "chat":
                subtasks.append(
                    {
                        "text": part,
                        "intent": result.intent,
                        "tools": result.tool_hints,
                    }
                )
        return subtasks if len(subtasks) > 1 else []

    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        return {
            "categories": list(self.SIGNALS.keys()),
            "method": "multi-signal scoring",
        }
