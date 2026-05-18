import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger("NEXUS_REASONING_TOOL")

class ReasoningTool:
    """
    NEXUS REASONING TOOL (v1.0)
    Explicit multi-step reasoning using the Mixture of Architects (MoA).
    """
    def __init__(self, loop=None):
        self.loop = loop

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "name": "reason",
            "description": "Perform deep multi-step reasoning or planning for a complex task using multiple frontier models (MoA).",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The complex task or problem to reason about."
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context or constraints."
                    }
                },
                "required": ["task"]
            }
        }

    def execute(self, task: str, context: str = "") -> str:
        """
        Sync wrapper for async MoA solve.
        """
        try:
            from core.kernel import get_nexus_kernel
            moa = get_nexus_kernel().moa
            
            full_task = f"{task}\n\n[CONTEXT]: {context}" if context else task
            
            # Since MoA solve is async, we run it in a new event loop or use the existing one
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            result = loop.run_until_complete(moa.solve(full_task))
            return f"### [DEEP_REASONING_RESULT]:\n{result}"
        except Exception as e:
            return f"[REASONING_ERROR]: {str(e)}"
