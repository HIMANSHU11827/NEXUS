"""
NEXUS CONTEXT COMPRESSOR (PORT FROM HERMES-AGENT)
Automatic context window compression for long conversations.
Prevents God-Architect token-limit crashes.
"""

import logging
import time
import json
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION] Earlier turns in this conversation were compacted "
    "to save context space. Use the summary below and the current state to continue:"
)

# Minimum tokens for the summary output
_MIN_SUMMARY_TOKENS = 2000
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 12_000
_CHARS_PER_TOKEN = 4
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"

class NexusContextCompressor:
    """
    Compresses conversation context when approaching the model's context limit.
    """

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20240620",
        threshold_percent: float = 0.70,
        protect_first_n: int = 3,
        protect_last_n: int = 20,
        summary_target_ratio: float = 0.20,
    ):
        self.model = model
        self.threshold_percent = threshold_percent
        self.protect_first_n = protect_first_n
        self.protect_last_n = protect_last_n
        self.summary_target_ratio = max(0.10, min(summary_target_ratio, 0.80))
        
        # Hard-coded for Claude-3-5/Sonnet/Opus which have 200k
        self.context_length = 200_000 
        self.threshold_tokens = int(self.context_length * threshold_percent)
        self.compression_count = 0

        target_tokens = int(self.threshold_tokens * self.summary_target_ratio)
        self.tail_token_budget = target_tokens
        self.max_summary_tokens = min(int(self.context_length * 0.05), _SUMMARY_TOKENS_CEILING)
        self._previous_summary: Optional[str] = None

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Rough estimate of tokens in messages."""
        text = json.dumps(messages)
        return len(text) // _CHARS_PER_TOKEN

    def should_compress(self, messages: List[Dict[str, Any]]) -> bool:
        """Check if context exceeds the compression threshold."""
        return self._estimate_tokens(messages) >= self.threshold_tokens

    def _prune_old_tool_results(
        self, messages: List[Dict[str, Any]], protect_tail_count: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Replace old tool result contents with a short placeholder."""
        if not messages:
            return messages, 0

        result = [m.copy() for m in messages]
        pruned = 0
        prune_boundary = len(result) - protect_tail_count

        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = str(msg.get("content", ""))
            if len(content) > 200:
                result[i] = {**msg, "content": _PRUNED_TOOL_PLACEHOLDER}
                pruned += 1

        return result, pruned

    def _generate_summary(self, turns_to_summarize: List[Dict[str, Any]]) -> Optional[str]:
        """Generate a structured summary of conversation turns using NEXUS ModelRouter."""
        from core.providers.router import ModelRouter
        router = ModelRouter()
        content_to_summarize = json.dumps(turns_to_summarize, indent=2)
        
        if self._previous_summary:
            prompt = f"""Update the context compaction summary. 
PREVIOUS SUMMARY:
{self._previous_summary}

NEW TURNS:
{content_to_summarize}

Return a structured summary with:
## Goal
## Progress (Done/In Progress)
## Key Decisions
## Relevant Files
## Next Steps
"""
        else:
            prompt = f"""Summarize these conversation turns for context compaction.
TURNS:
{content_to_summarize}

Use structure:
## Goal
## Progress (Done/In Progress)
## Key Decisions
## Relevant Files
## Next Steps
"""
        try:
            summary = router.generate(
                prompt=prompt, 
                system_prompt="You are the NEXUS Context Compressor. Be exhaustive but concise.",
                ignore_compression=True
            )
            self._previous_summary = summary
            return f"{SUMMARY_PREFIX}\n{summary}"
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return None

    def _sanitize_tool_pairs(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fix orphaned tool_call / tool_result pairs."""
        surviving_call_ids = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    cid = tc.get("id") if isinstance(tc, dict) else getattr(tc, 'id', None)
                    if cid: surviving_call_ids.add(cid)

        result_call_ids = set()
        for msg in messages:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid: result_call_ids.add(cid)

        # Remove orphaned results
        orphaned_results = result_call_ids - surviving_call_ids
        if orphaned_results:
            messages = [m for m in messages if not (m.get("role") == "tool" and m.get("tool_call_id") in orphaned_results)]

        # Add stub results for orphaned calls
        missing_results = surviving_call_ids - result_call_ids
        if missing_results:
            patched = []
            for msg in messages:
                patched.append(msg)
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        cid = tc.get("id") if isinstance(tc, dict) else getattr(tc, 'id', None)
                        if cid in missing_results:
                            patched.append({
                                "role": "tool",
                                "content": "[Result archived in summary]",
                                "tool_call_id": cid,
                            })
            messages = patched

        return messages

    def compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Main entry point for compressing messages."""
        if not self.should_compress(messages):
            return messages

        logger.info(f"[NEXUS_COMPRESSOR]: Compressing {len(messages)} turns...")
        
        # 1. Prune tools
        messages, _ = self._prune_old_tool_results(messages, self.protect_last_n)
        
        # 2. Boundaries
        compress_start = self.protect_first_n
        compress_end = len(messages) - self.protect_last_n
        
        if compress_start >= compress_end:
            return messages

        turns_to_summarize = messages[compress_start:compress_end]
        summary = self._generate_summary(turns_to_summarize)
        
        # 3. Assemble
        compressed = messages[:compress_start]
        if summary:
            # --- V10 HIERARCHICAL MEMORY UPGRADE ---
            from knowledge.vault import KnowledgeVault
            vault = KnowledgeVault()
            vault.add_fact(
                "NEXUS_SYSTEM", 
                "episodic_history", 
                f"[CONTEXT_ARCHIVE]: {summary}", 
                importance=8.0
            )
            compressed.append({"role": "user", "content": summary})
        
        compressed.extend(messages[compress_end:])
        
        # 4. Clean up tool mismatches
        compressed = self._sanitize_tool_pairs(compressed)
        
        self.compression_count += 1
        logger.info(f"[NEXUS_COMPRESSOR]: Compaction complete with Semantic Vault persistence.")
        
        return compressed
