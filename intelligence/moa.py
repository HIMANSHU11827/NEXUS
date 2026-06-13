import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from providers.router import ModelRouter

logger = logging.getLogger(__name__)

class MixtureOfArchitects:
    """
    NEXUS MOA (Mixture of Architects)
    Implements a 2-layer intelligence aggregation system.
    Layer 1: Parallel diverse reasoning from multiple frontier models.
    Layer 2: Aggregator synthesis to produce the definitive God-Tier answer.
    """
    
    DEFAULT_REFERENCES = [
        "anthropic/claude-3.5-sonnet",
        "google/gemini-1.5-pro",
        "openai/gpt-4o",
        "deepseek/deepseek-chat"
    ]
    
    DEFAULT_AGGREGATOR = "anthropic/claude-3.5-sonnet"

    def __init__(self, router: ModelRouter):
        self.router = router

    async def _query_single_architect(self, model: str, prompt: str) -> Dict[str, Any]:
        """Query a single model and return its contribution."""
        try:
            logger.info(f"🧠 [MOA]: Querying {model}...")
            # Use the existing router to handle different model providers
            # Note: ModelRouter.generate is currently synchronous, but we'll wrap it
            import asyncio
            response = await asyncio.to_thread(self.router.generate, prompt=prompt, model=model)
            return {
                "model": model,
                "content": response,
                "success": True
            }
        except Exception as e:
            logger.error(f"❌ [MOA]: {model} failed: {e}")
            return {
                "model": model,
                "content": str(e),
                "success": False
            }

    async def solve(self, task: str, reference_models: List[str] = None) -> str:
        """
        Solves a complex task using multi-model collaborative reasoning.
        """
        start_time = datetime.now()
        models = reference_models or self.DEFAULT_REFERENCES
        
        logger.info(f"🚀 [NEXUS-MOA]: Initiating collaboration between {len(models)} architects...")

        # Layer 1: Parallel Reasoning
        tasks = [self._query_single_architect(m, task) for m in models]
        results = await asyncio.gather(*tasks)
        
        successful_responses = [r["content"] for r in results if r["success"]]
        
        if not successful_responses:
            return "❌ [MOA_FAILURE]: All reference architects failed to respond."

        # Layer 2: Aggregation
        logger.info(f"📥 [NEXUS-MOA]: Synthesizing {len(successful_responses)} perspectives...")
        
        aggregation_prompt = f"""
        You are the NEXUS Supreme Aggregator. Below are responses from multiple frontier AI models to a complex task.
        Your goal is to synthesize these responses into a single, definitive, and high-quality solution.
        Critically evaluate the insights, fix any contradictions, and combine the best elements of each approach.
        
        TASK:
        {task}
        
        INDIVIDUAL ARCHITECT RESPONSES:
        {chr(10).join([f"--- Architect {i+1} ---\n{resp}" for i, resp in enumerate(successful_responses)])}
        
        FINAL DEFINITIVE SOLUTION:
        """
        
        final_solution = await asyncio.to_thread(
            self.router.generate, prompt=aggregation_prompt
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ [NEXUS-MOA]: Task solved in {duration:.2f}s using {len(successful_responses)} brains.")
        
        return final_solution
