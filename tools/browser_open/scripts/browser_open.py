"""Tool: browser_open — The user is likely trying to open/run the dino_game.html file in a browser for testing, but no browser launch capability is present."""

import json
from typing import Any, Dict


def execute(params: Dict[str, Any]) -> str:
    """Execute the tool with the given parameters."""
    return json.dumps({"status": "ok", "tool": "browser_open", "result": "not yet implemented"})
