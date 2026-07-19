import logging

logger = logging.getLogger("NEXUS_INDEXER")

class NexusSemanticIndexer:
    def __init__(self, root: str = "."):
        self.root = root
        logger.info("NexusSemanticIndexer initialized (stub — no semantic indexing)")
