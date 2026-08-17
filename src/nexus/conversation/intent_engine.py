import logging
import re
from enum import Enum

logger = logging.getLogger("NEXUS_INTENT")


class NexusIntent(str, Enum):
    """Stable intent categories consumed by provider routing.

    This is deliberately lightweight: routing must not require a model call or
    import the provider stack that owns the router.
    """

    MISSION = "mission"
    VISION = "vision"
    DIAGNOSTIC = "diagnostic"
    COGNITION = "cognition"
    CHAT = "chat"


class IntentEngine:
    def __init__(self, router=None):
        self.router = router

    def classify(self, query: str) -> dict:
        """Classify a request without invoking the model provider.

        The result remains a dictionary for compatibility with existing
        callers.  Routing only needs a conservative complexity signal, so
        explicit high-signal phrases take precedence over generic words.
        """
        text = str(query or "").strip().lower()
        if not text:
            return {"intent": NexusIntent.CHAT.value, "confidence": 1.0, "needs_tools": False}

        groups = (
            (NexusIntent.MISSION, (
                r"\b(implement|build|create|refactor|upgrade|migrate|deploy|ship)\b",
                r"\b(fix|repair|debug)\b.*\b(project|repository|application|system)\b",
                r"\b(step[- ]by[- ]step|end[- ]to[- ]end|long[- ]running|autonomous)\b",
            )),
            (NexusIntent.VISION, (
                r"\b(architecture|roadmap|design|strategy|system design)\b",
                r"\b(compare|benchmark|audit|deep research|thoroughly analyze)\b",
            )),
            (NexusIntent.DIAGNOSTIC, (
                r"\b(debug|diagnose|why|failing|failure|broken|error|exception|traceback|test)\b",
                r"\b(not working|doesn.t work|investigate|inspect)\b",
            )),
            (NexusIntent.COGNITION, (
                r"\b(explain|reason|analyze|understand|summarize|evaluate)\b",
            )),
        )
        for intent, patterns in groups:
            if any(re.search(pattern, text) for pattern in patterns):
                return {
                    "intent": intent.value,
                    "confidence": 0.8,
                    "needs_tools": intent in {
                        NexusIntent.MISSION,
                        NexusIntent.VISION,
                        NexusIntent.DIAGNOSTIC,
                    },
                }
        return {"intent": NexusIntent.CHAT.value, "confidence": 0.5, "needs_tools": False}


__all__ = ["IntentEngine", "NexusIntent"]
