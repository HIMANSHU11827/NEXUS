import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class NeuralSymbolicProtocol:
    """
    NEXUS NSP v1.0 — Cognitive Symbol Table.
    Maps verbose system instructions to ultra-compact Unicode Logic Tags.
    Reduces Language Waste in system prompts by up to 80%.
    """

    def __init__(self):
        # The 'Sacred Symbol Table' — Maps symbols to their expansion
        self.symbol_table = {
            "▚": "VALID_JSON_ONLY: Ensure all tool calls are strictly JSON formatted.",
            "🌀": "SIMULATE_FIRST: Draft the logic in inner monologue before acting.",
            "📐": "PLAN_MISSION: Create a multi-step objective map.",
            "🚀": "EXECUTE_SOVEREIGN: Run terminal and file commands with high confidence.",
            "🧠": "LEARN_ADAPT: Synthesize a lesson learned after every success/failure.",
            "🛡️": "AUDIT_SAFETY: Red-team the proposed code for security flaws.",
            "🧬": "EVOLVE_CORE: Surgically refactor the project's own source code.",
            "📟": "HARDWARE_AWARE: Monitor CPU/RAM/Thermal stats before heavy tasks.",
            "📜": "MEMORY_RECALL: Inject past experiences from the encrypted vault.",
            "📅": "STRATEGIC_DEPTH: Focus on long-horizon multi-day goals."
        }

    def compress(self, text: str) -> str:
        """Converts natural language instructions into Symbolic Shorthand."""
        compressed = text
        for symbol, expansion in self.symbol_table.items():
            # If the instruction contains the expansion, replace it with the symbol
            if expansion in text:
                compressed = compressed.replace(expansion, symbol)
        return compressed

    def get_symbol_legend(self) -> str:
        """Returns the legend for the LLM system prompt."""
        legend = []
        for sym, exp in self.symbol_table.items():
            legend.append(f"{sym}:{exp.split(':')[0]}") # Only show the keyword for brevity
        return "|".join(legend)

    def get_instruction_for_symbol(self, symbol: str) -> str:
        """Expands a symbol back into its full tactical instruction."""
        return self.symbol_table.get(symbol, "[UNKNOWN_DECODE_ERR]")
