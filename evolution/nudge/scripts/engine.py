"""Nudge Engine — periodic self-reminders for NEXUS."""
__version__ = "1.0.0"
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from providers.router import ModelRouter
logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

class NudgeEngine:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.state_path = os.path.join(self.root, "configs", "nudge_engine.json")
        self.log_path = os.path.join(self.root, "logs", "nudges.jsonl")
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def should_nudge(self, nudge_type: str = "skill", interval: int = 600) -> bool:
        state = self._load_state()
        last = state.get(nudge_type, 0)
        return time.time() - last > interval

    def generate_nudge(self, context: str = "") -> Optional[str]:
        if not self.should_nudge():
            return None
        try:
            router = _get_router()
            prompt = f"""[NUDGE_GENERATION]
Based on this context, suggest ONE thing NEXUS could improve:

{context[:500]}

Return a short actionable nudge (1-2 sentences).
"""
            result = router.generate(messages=[{"role": "user", "content": prompt}])
            self._mark_nudged("improvement")
            self._log_nudge(result)
            return result
        except Exception as e:
            logger.debug(f"Nudge generation failed: {e}")
            return None

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _mark_nudged(self, nudge_type: str):
        state = self._load_state()
        state[nudge_type] = time.time()
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)

    def _log_nudge(self, nudge_text: str):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"nudge": nudge_text, "timestamp": time.time()}) + "\n")
        except Exception:
            pass
