"""
NEXUS FILE-CENTRIC PERSISTENCE (v14.0)
Externalizes agent state to the file system to enable unbounded task horizon.
Inspired by InfiAgent and 2027-horizon research.
"""

import os
import json
import logging
import time

logger = logging.getLogger(__name__)

class NexusFilePersistence:
    """
    Manages infinite state by swapping memory to disk.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.state_dir = os.path.join(self.root, "logs", "context", "persistence")
        os.makedirs(self.state_dir, exist_ok=True)

    def checkpoint_session(self, session_id: str, messages: list):
        """Dumps a reasoning session to disk for infinite recall."""
        path = os.path.join(self.state_dir, f"{session_id}.json")
        data = {
            "timestamp": time.time(),
            "turns": len(messages),
            "messages": messages
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[PERSISTENCE]: Session {session_id} checkpointed to disk.")

    def load_session(self, session_id: str) -> list:
        """Loads an archived session from disk."""
        path = os.path.join(self.state_dir, f"{session_id}.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f).get("messages", [])
        return []

    def get_context_size(self, session_id: str) -> int:
        """Returns the size of the archived context in bytes."""
        path = os.path.join(self.state_dir, f"{session_id}.json")
        if os.path.exists(path):
            return os.path.getsize(path)
        return 0
