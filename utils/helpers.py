import re
import datetime
from typing import List, Dict, Any, Optional


class NexusHelpers:
    """
    NEXUS HELPER UTILS 1.0 (SWISS-ARMY-KNIFE)
    Shared utility functions for all NEXUS modules.

    Features:
    - Text Cleaning & Sanitization.
    - JSON-Proof Parsing.
    - Semantic Similarity Scorers.
    """

    @staticmethod
    def get_timestamp() -> str:
        """Universal timestamp for logs and checkpoints."""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def clean_llm_json(raw_text: str) -> Dict[str, Any]:
        """Strips out markdown code blocks and returns clean JSON."""
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            return eval(match.group())
        return {}


if __name__ == "__main__":
    print(f"Current Time: {NexusHelpers.get_timestamp()}")
    test_json = "```json\n{'status': 'ok'}\n```"
    print(f"Cleaned JSON: {NexusHelpers.clean_llm_json(test_json)}")
