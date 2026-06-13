"""
NEXUS INTENT & PROACTIVE ENGINE (v17.0)
Predicts user intent and long-horizon goals to prepare the system's focus.
"""

import re
import logging
import asyncio
from typing import List, Dict, Any
from providers.router import ModelRouter

logger = logging.getLogger(__name__)

class NexusIntentEngine:
    """
    Predicts what the user wants before they even ask.
    """

    def __init__(self):
        self.router = ModelRouter()

    async def predict_horizon(self, current_task: str, history: List[Dict[str, str]]) -> List[str]:
        """
        Predicts the next 3 logical steps the user will likely request.
        """
        history_summary = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in history[-5:]])
        
        prompt = f"""[INTENT_HORIZON_ANALYSIS]
TASK: {current_task}
HISTORY: {history_summary}

Predict the next 3 LIKELY requests the user will make. 
Format: [Request 1, Request 2, Request 3]"""

        messages = [
            {"role": "system", "content": "You are the Nexus Oracle."},
            {"role": "user", "content": prompt}
        ]
        res = await asyncio.to_thread(self.router.generate, messages=messages)
        # Parse the prediction items: [Request 1, Request 2, Request 3]
        matches = re.findall(r"\[(.*?),(.*?),(.*?)\]", res)
        if matches:
            return [m.strip() for m in matches[0]]
        
        # Fallback to newline split
        return [line.strip() for line in res.split("\n") if line.strip() and not line.startswith("[")][:3]

    def generate_proactive_suggestion(self, predictions: List[str]) -> str:
        """Returns a high-fidelity suggestion for the user."""
        if not predictions: return ""
        return f"Based on your workflow, shall I begin {predictions[0]}?"
