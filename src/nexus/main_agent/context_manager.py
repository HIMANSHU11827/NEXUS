"""Context Manager - V1 context management integration for NEXUS V5.

This module implements context management features from V1:
- Context file loading (AGENTS.md, CLAUDE.md, .cursorrules)
- Context compaction with token limits
- 3-tier prompt cache
- Context scrubbing
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ContextConfig:
    """Configuration for context management."""
    context_token_limit: int = 128000
    budget_tokens: Optional[int] = None
    compact_threshold: int = 20
    compact_keep: int = 6
    context_file_names: tuple = (
        "NEXUS.md",
        "AGENTS.md", "agents.md",
        "CLAUDE.md", "claude.md",
        ".cursorrules",
        ".cursor/rules/*.mdc",
    )


@dataclass
class ContextSnapshot:
    """Snapshot of loaded context."""
    files_loaded: List[str] = field(default_factory=list)
    total_tokens: int = 0
    compacted: bool = False
    cached: bool = False


class ContextManager:
    """Context manager with V5 integration."""

    def __init__(self, root_dir: str, config: Optional[ContextConfig] = None):
        self.root_dir = root_dir
        self.config = config or ContextConfig()
        self.logger = logging.getLogger("nexus.v5.context")
        
        # Context cache
        self._stable_prompt_cache: Optional[str] = None
        self._stable_prompt_built = False
        self._context_cache: Dict[str, str] = {}
        
        # Context file paths
        self._context_files: List[str] = []
        self._discover_context_files()

    def _discover_context_files(self):
        """Discover context files in the project."""
        discovered: Dict[str, str] = {}
        for pattern in self.config.context_file_names:
            if "*" in pattern:
                # Glob pattern
                import glob
                matches = glob.glob(os.path.join(self.root_dir, pattern))
                for match in matches:
                    discovered[os.path.normcase(os.path.abspath(match))] = os.path.abspath(match)
            else:
                # Direct file
                path = os.path.join(self.root_dir, pattern)
                if os.path.exists(path):
                    discovered[os.path.normcase(os.path.abspath(path))] = os.path.abspath(path)
        self._context_files = list(discovered.values())
        
        self.logger.debug(f"Discovered {len(self._context_files)} context")

    async def load_context(self) -> ContextSnapshot:
        """Load context from discovered files.
        
        Returns:
            ContextSnapshot with loaded context info
        """
        return await asyncio.to_thread(self._load_context_sync)

    def _load_context_sync(self) -> ContextSnapshot:
        """Perform context discovery and file reads in a worker thread."""
        snapshot = ContextSnapshot()
        self._context_cache.clear()
        self._context_files = []
        self._discover_context_files()
        self._stable_prompt_cache = None
        self._stable_prompt_built = False
        
        for file_path in self._context_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self._context_cache[file_path] = content
                    snapshot.files_loaded.append(file_path)
                    # Estimate tokens (rough estimate: 4 chars per token)
                    snapshot.total_tokens += len(content) // 4
            except Exception as e:
                self.logger.warning(f"Failed to load context file {file_path}: {e}")
        
        self.logger.info(f"Loaded context from {len(snapshot.files_loaded)} files")
        return snapshot

    def get_context(self) -> str:
        """Get combined context string."""
        if not self._context_cache:
            return ""
        
        # Combine all context files
        context_parts = []
        for file_path, content in self._context_cache.items():
            filename = os.path.basename(file_path)
            context_parts.append(f"=== {filename} ===\n{content}")
        
        return "\n\n".join(context_parts)

    def should_compact(self, message_count: int) -> bool:
        """Check if context should be compacted."""
        return message_count >= self.config.compact_threshold

    def compact_context(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Compact context via the shared call/result-safe compactor.

        Delegates to ``context.compact_messages`` — the same compactor the live
        V5 loop uses — so a tool_call is NEVER split from its tool_result. Any
        error falls back to the legacy head/tail summary below. Signature stays
        ``compact_context(messages) -> List[Dict[str, str]]``.
        """
        if not isinstance(messages, list) or not messages:
            return messages
        try:
            from nexus.context import compact_messages
            budget = self.config.budget_tokens or self.config.context_token_limit
            compacted, dropped = compact_messages(
                messages, budget_tokens=budget, keep_recent=self.config.compact_keep
            )
            if isinstance(compacted, list):
                if dropped:
                    self.logger.info(f"Compacted {dropped} messages via shared compactor")
                return compacted
        except Exception:
            pass
        return self._compact_legacy(messages)

    def _compact_legacy(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Legacy fallback: keep recent, summarize older via ``_summarize_messages``."""
        if len(messages) <= self.config.compact_keep:
            return messages

        # Keep recent messages, summarize older ones
        recent = messages[-self.config.compact_keep:]
        older = messages[:-self.config.compact_keep]

        if older:
            summary = self._summarize_messages(older)
            compacted = [{"role": "system", "content": summary}] + recent
            self.logger.info(f"Compacted {len(older)} messages into summary")
            return compacted

        return messages

    def _summarize_messages(self, messages: List[Dict[str, str]]) -> str:
        """Summarize a list of messages."""
        # Simple summary (in real implementation, would use LLM)
        user_messages = [m for m in messages if m.get("role") == "user"]
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        
        summary_parts = [
            "Compacted conversation:",
            f"- {len(user_messages)} user messages",
            f"- {len(assistant_messages)} assistant responses",
            f"- Last topic: {messages[-1].get('content', '')[:100] if messages else 'None'}"
        ]
        
        return "\n".join(summary_parts)

    # ────────────────────────────────────────────────────────────────────────
    # COMPACTION WITH BOUNDARY EVENT (roadmap item 11)
    # ────────────────────────────────────────────────────────────────────────

    def _compaction_boundary(
        self, messages: List[Dict[str, str]], budget_ratio: float = 0.83
    ) -> Dict[str, Any]:
        """Compute a head/tail compaction boundary for *messages*.

        Always keeps the first (system) message and drops the oldest tail
        until the kept length is at most ``max(8, len * budget_ratio)`` with
        a floor of the first message plus the last 8. Returns the kept tail,
        the dropped count and a canonical ``context.compacted`` boundary
        event (``None`` when nothing is dropped). Never raises.
        """
        if not isinstance(messages, list):
            return {"kept": messages or [], "dropped": 0, "boundary_event": None}
        total = len(messages)
        if total <= 1:
            return {"kept": messages, "dropped": 0, "boundary_event": None}
        try:
            keep_limit = max(8, int(total * budget_ratio))
            if keep_limit < 9:
                keep_limit = 9
        except Exception:
            keep_limit = total
        drop_count = total - keep_limit
        if drop_count <= 0:
            return {"kept": messages, "dropped": 0, "boundary_event": None}
        kept = [messages[0]] + messages[drop_count + 1:]
        dropped = total - len(kept)
        boundary_event = {
            "event_type": "context.compacted",
            "kind": "context",
            "part_type": "other",
            "status": "done",
            "dropped": dropped,
            "kept": len(kept),
            "title": "Context compacted",
        }
        return {"kept": kept, "dropped": dropped, "boundary_event": boundary_event}

    def _compact_context(
        self, messages: List[Dict[str, str]], budget_ratio: float = 0.83
    ) -> List[Dict[str, str]]:
        """Compact *messages* head/tail and prepend the boundary marker.

        The synthetic boundary marker (a system message naming the dropped
        count) is placed at the front of the kept tail so the model sees the
        compaction. Returns the input unchanged on any problem; never raises.
        """
        try:
            boundary = self._compaction_boundary(messages, budget_ratio)
            kept = boundary.get("kept") or []
            dropped = boundary.get("dropped") or 0
            if dropped <= 0 or not isinstance(kept, list):
                return messages if isinstance(messages, list) else kept
            marker = {
                "role": "system",
                "content": (
                    f"[context compacted: {dropped} earlier messages dropped] "
                    "[boundary]"
                ),
            }
            return [marker] + kept
        except Exception:
            if isinstance(messages, list):
                return messages
            return list(messages) if messages else []

    def build_stable_prompt(self, system_prompt: str) -> str:
        """Build stable prompt with context.
        
        Args:
            system_prompt: Base system prompt
        
        Returns:
            Combined prompt with context
        """
        if self._stable_prompt_built and self._stable_prompt_cache:
            return self._stable_prompt_cache
        
        context = self.get_context()
        
        if context:
            combined = f"{system_prompt}\n\n=== PROJECT CONTEXT ===\n{context}"
        else:
            combined = system_prompt
        
        self._stable_prompt_cache = combined
        self._stable_prompt_built = True
        
        return combined

    def scrub_context(self, text: str) -> str:
        """Scrub sensitive information from context.
        
        Args:
            text: Text to scrub
        
        Returns:
            Scrubbed text
        """
        # Simple scrubbing (in real implementation, would use more sophisticated methods)
        # Remove API keys, passwords, etc.
        import re
        
        # Remove potential API keys
        text = re.sub(r'["\']?[A-Za-z0-9]{20,}["\']?', '[REDACTED]', text)
        
        # Remove email addresses
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        
        return text

    def clear_cache(self):
        """Clear context cache."""
        self._context_cache.clear()
        self._stable_prompt_cache = None
        self._stable_prompt_built = False
        self.logger.info("Context cache cleared")
