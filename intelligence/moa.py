import logging

logger = logging.getLogger("NEXUS_MOA")

class MixtureOfArchitects:
    def __init__(self, base_router):
        self.base_router = base_router
        logger.info("MixtureOfArchitects initialized (stub — no multi-agent aggregation)")

    def aggregate(self, messages: list) -> dict:
        logger.warning("MixtureOfArchitects.aggregate called but not implemented")
        return {"choices": [{"message": {"content": ""}}]}
