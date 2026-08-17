import ast
import datetime
import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger("nexus.helpers")


class NexusHelpers:
    @staticmethod
    def get_timestamp() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def clean_llm_json(raw_text: str) -> Dict[str, Any]:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                try:
                    result = ast.literal_eval(match.group())
                    if isinstance(result, dict):
                        return result
                except (ValueError, SyntaxError) as e:
                    logger.debug("clean_llm_json parse failed: %s", e)
        return {}


if __name__ == "__main__":
    print(f"Current Time: {NexusHelpers.get_timestamp()}")
    test_json = "```json\n{'status': 'ok'}\n```"
    print(f"Cleaned JSON: {NexusHelpers.clean_llm_json(test_json)}")
