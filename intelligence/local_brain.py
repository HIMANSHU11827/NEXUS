import logging

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

class NexusLocalBrain:
    def __init__(self, root: str):
        self.root = root
        logger.info("NexusLocalBrain initialized (stub — no offline inference)")

    def scan_image(self, path: str) -> str:
        logger.warning(f"NexusLocalBrain.scan_image called but not implemented: {path}")
        return "[STUB] Local brain image scanning not implemented"
