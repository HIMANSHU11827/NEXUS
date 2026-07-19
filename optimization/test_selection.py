import logging

logger = logging.getLogger("NEXUS_TEST_SELECTION")

class TestSelector:
    def __init__(self, root: str):
        self.root = root
        logger.info("TestSelector initialized (stub — no test selection)")

    def select_tests(self, changed_files: list) -> list:
        return []
