import logging

logger = logging.getLogger("NEXUS_INTENT")

class IntentEngine:
    def __init__(self, router=None):
        self.router = router

    def classify(self, query: str) -> dict:
        logger.debug("IntentEngine.classify (stub) — returning default chat intent")
        return {"intent": "chat", "confidence": 0.0, "needs_tools": False}
