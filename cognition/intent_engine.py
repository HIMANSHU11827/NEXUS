"""
NEXUS INTENT ENGINE 1.0
High-fidelity intent recognition for sovereign autonomous agents.
Uses a hybrid strategy of fast-path heuristics and neural classification.
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NEXUS_INTENT")


class NexusIntent(str, Enum):
    MISSION = "mission"      # Core engineering, coding, task execution
    DIAGNOSTIC = "diagnostic"  # System health, errors, debugging nexus
    VISION = "vision"        # Visual tasks, screenshots, UI analysis
    COGNITION = "cognition"  # Meta-reasoning, intent, memory, strategy
    SOCIAL = "social"        # Chat, personality, general discussion
    UTILITY = "utility"      # Basic shell, file ops, search
    UNKNOWN = "unknown"      # Out of scope or ambiguous


class IntentEngine:
    def __init__(self, router=None):
        self.router = router
        self.heuristics = {
            NexusIntent.VISION: ["vision", "screenshot", "camera", "image", "see", "look", "ui", "gui"],
            NexusIntent.DIAGNOSTIC: ["error", "logs", "health", "debug", "broken", "fix nexus", "audit", "status"],
            NexusIntent.UTILITY: ["ls", "cat", "grep", "find", "where is", "search file", "glob"],
            NexusIntent.SOCIAL: ["who are you", "hello", "hi", "how are you", "tell me a joke", "personality"],
            NexusIntent.COGNITION: ["intent", "memory", "strategy", "plan", "think", "reason"],
            NexusIntent.MISSION: ["write", "create", "implement", "build", "refactor", "code", "run", "file", "make", "add", "change", "develop", "test", "verify", "commit", "push", "pull", "git"],
        }

    def classify(self, text: str, context: Optional[List[Dict[str, str]]] = None) -> NexusIntent:
        del context
        text = text.lower().strip()
        if not text:
            return NexusIntent.UNKNOWN

        # Bypass recursive calls or classification prompts
        if "classify user intent" in text or "options:" in text:
            return NexusIntent.UNKNOWN

        for intent, keywords in self.heuristics.items():
            if any(keyword in text for keyword in keywords):
                logger.debug(f"[INTENT_HEURISTIC]: Matched {intent.value}")
                return intent

        if self.router:
            try:
                prompt = (
                    f"Classify user intent for: '{text}'\n"
                    f"Options: {', '.join(intent.value for intent in NexusIntent)}\n"
                    "Response: "
                )
                result = self.router.generate(prompt=prompt, max_tokens=10, temperature=0.0).strip().lower()
                for intent in NexusIntent:
                    if intent.value in result:
                        logger.info(f"[INTENT_NEURAL]: Classified as {intent.value}")
                        return intent
            except Exception as exc:
                logger.warning(f"Intent classification failed: {exc}")

        return NexusIntent.MISSION

    def get_strategy(self, intent: NexusIntent) -> Dict[str, Any]:
        """Return loop strategy parameters based on intent."""
        strategies = {
            NexusIntent.MISSION: {"max_turns": 20, "force_reasoning": True, "task_complexity": "complex"},
            NexusIntent.DIAGNOSTIC: {"max_turns": 10, "force_reasoning": False, "task_complexity": "simple"},
            NexusIntent.VISION: {"max_turns": 15, "force_reasoning": True, "task_complexity": "vision"},
            NexusIntent.SOCIAL: {"max_turns": 1, "force_reasoning": False, "task_complexity": "simple"},
            NexusIntent.COGNITION: {"max_turns": 5, "force_reasoning": True, "task_complexity": "meta"},
            NexusIntent.UTILITY: {"max_turns": 8, "force_reasoning": False, "task_complexity": "simple"},
            NexusIntent.UNKNOWN: {"max_turns": 5, "force_reasoning": False, "task_complexity": "simple"},
        }
        return strategies.get(intent, strategies[NexusIntent.MISSION])
