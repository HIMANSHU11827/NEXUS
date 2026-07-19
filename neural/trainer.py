import logging

logger = logging.getLogger("NEXUS_TRAINER")

class NexusTrainer:
    def __init__(self, root: str):
        self.root = root
        logger.info("NexusTrainer initialized (stub — no model training)")
