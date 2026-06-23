"""NEXUS INTENT & PROACTIVE ENGINE (v17.0)"""
import asyncio
import logging
import re
from typing import Dict, List, Optional
from providers.router import ModelRouter
logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

class NexusIntentEngine:
    async def predict_horizon(self, current_task: str, history: List[Dict[str, str]]) -> List[str]:
        router = _get_router()
        history_summary = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in history[-5:]])
        prompt = f"""[INTENT_HORIZON_ANALYSIS]
TASK: {current_task}
HISTORY: {history_summary}
Predict the next 3 LIKELY requests the user will make.
Format: [Request 1, Request 2, Request 3]"""
        try:
            result = router.generate(messages=[{"role": "user", "content": prompt}])
            matches = re.findall(r'\[(.*?)\]', result)
            if matches:
                return [m.strip() for m in matches[0].split(",")]
            return []
        except Exception:
            return []
