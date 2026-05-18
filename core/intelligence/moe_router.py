"""
NEXUS MIXTURE OF EXPERTS (MOE) ROUTER (v17.0)
Specialized expert selection for complex sub-tasks.
Categories: [CODING, RESEARCH, SECURITY, VISION, DATA]
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional
from core.providers.router import ModelRouter

logger = logging.getLogger(__name__)

class NexusMoERouter:
    """
    Orchestrates specialized 'Experts' for high-precision tasks.
    """

    def __init__(self, root_dir: Optional[str] = None):
        self.base_router = ModelRouter()
        self.experts = {
            "CODING": "claude-3-5-sonnet", # The heavy coder (LARGE/EXTREME)
            "RESEARCH": "gpt-4o",          # The broad researcher (LARGE)
            "SECURITY": "o1-preview",      # The reasoning specialist (EXTREME)
            "VISION": "nexus-vlm-100m",    # Native vision grounding (NANO/MICRO)
            "LOGIC": "deepseek-reasoner",  # Deep reasoning expert (EXTREME)
            "NANO": "qwen3.5-0.8b-uncensored-opus-distill"   # High-speed local formatting/intent (NANO)
        }

    def set_override(self, provider_id: str):
        """Forces the base router to use a specific provider."""
        self.base_router.set_override(provider_id)

    def generate(self, messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        """Delegates generation to the base router."""
        return self.base_router.generate(messages=messages, **kwargs)

    def stream_generate(self, messages: Optional[List[Dict[str, str]]] = None, **kwargs):
        """Delegates streaming generation to the base router."""
        yield from self.base_router.stream_generate(messages=messages, **kwargs)

    async def route_to_expert(self, task_desc: str) -> str:
        """
        Classifies the task and routes it to the specialized expert.
        """
        classification_prompt = f"Classify this task into one of [CODING, RESEARCH, SECURITY, VISION, LOGIC]:\nTASK: {task_desc}"
        messages = [{"role": "user", "content": classification_prompt}]
        category = await asyncio.to_thread(self.base_router.generate, messages=messages)
        
        category = category.strip().upper()
        expert_model = self.experts.get(category, "gpt-4o") # Default
        
        logger.info(f"[MOE_ROUTER]: Task classified as {category}. Routing to {expert_model}.")
        return expert_model

    async def solve_with_consensus(self, task_desc: str, expert_category: str) -> str:
        """
        Uses MoA (Mixture of Architects) restricted to the best specialized experts.
        """
        from core.kernel import get_nexus_kernel
        moa = get_nexus_kernel().moa
        
        expert = self.experts.get(expert_category, "gpt-4o")
        logger.info(f"🧠 [MOE_CONSENSUS]: Solving '{task_desc[:50]}...' with {expert} lead.")
        
        # We can pass the expert as the first reference model to give it priority
        return await moa.solve(task_desc, reference_models=[expert] + moa.DEFAULT_REFERENCES)
