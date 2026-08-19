"""Episodic memory stream — scored retrieval for long-horizon context.

Inspired by Generative Agents (Smallville) and Voyager: memories are stored
as an append-only stream with scored retrieval using:

    score = recency_weight × relevance_weight × importance_weight

- **Recency**: Exponential decay from timestamp (recent = higher score)
- **Relevance**: Keyword/semantic overlap with current query
- **Importance**: LLM-assigned or heuristic importance score (1-10)

On failure or reflection, the agent synthesizes higher-level insights
("root cause: X", "lesson learned: Y") and stores them as new memories,
creating a layered abstraction over time.

Memories are persisted as JSONL under .nexus/v5/episodic_memory.jsonl.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 5000
_DECAY_HALF_LIFE_HOURS = 24  # Memories lose half relevance every 24 hours
_DEFAULT_RECENCY_WEIGHT = 1.0
_DEFAULT_RELEVANCE_WEIGHT = 2.0
_DEFAULT_IMPORTANCE_WEIGHT = 1.5


@dataclass
class EpisodicMemory:
    """One episodic memory entry."""
    memory_id: str
    content: str
    timestamp: float
    importance: float  # 0.0 - 1.0
    memory_type: str  # "observation", "reflection", "insight", "failure", "success"
    tags: List[str] = field(default_factory=list)
    source_turn: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "memory_type": self.memory_type,
            "tags": self.tags,
            "source_turn": self.source_turn,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodicMemory":
        return cls(
            memory_id=str(data.get("memory_id", "")),
            content=str(data.get("content", "")),
            timestamp=float(data.get("timestamp", 0)),
            importance=float(data.get("importance", 0.5)),
            memory_type=str(data.get("memory_type", "observation")),
            tags=list(data.get("tags", [])),
            source_turn=str(data.get("source_turn", "")),
            metadata=dict(data.get("metadata", {})),
        )


class EpisodicMemoryStore:
    """Append-only episodic memory with scored retrieval.

    Memories are persisted as JSONL and loaded into memory on construction.
    Retrieval scores memories using the three-factor model from Generative
    Agents: recency × relevance × importance.
    """

    def __init__(
        self,
        root_dir: str,
        session_id: str = "default",
        *,
        recency_weight: float = _DEFAULT_RECENCY_WEIGHT,
        relevance_weight: float = _DEFAULT_RELEVANCE_WEIGHT,
        importance_weight: float = _DEFAULT_IMPORTANCE_WEIGHT,
    ):
        self.root_dir = root_dir
        self.session_id = session_id
        self._recency_weight = recency_weight
        self._relevance_weight = relevance_weight
        self._importance_weight = importance_weight
        self._memories: List[EpisodicMemory] = []
        self._memory_path = self._resolve_path()
        self._load()

    def _resolve_path(self) -> str:
        base = os.path.join(self.root_dir, ".nexus", "v5")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "episodic_memory.jsonl")

    def _load(self) -> None:
        """Load memories from disk."""
        try:
            if not os.path.exists(self._memory_path):
                return
            with open(self._memory_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._memories.append(EpisodicMemory.from_dict(data))
                    except (json.JSONDecodeError, ValueError):
                        continue
            # Keep only the newest N memories
            if len(self._memories) > _MAX_MEMORIES:
                self._memories = self._memories[-_MAX_MEMORIES:]
        except Exception as exc:
            logger.debug("episodic memory load failed: %s", exc)

    def _save(self) -> None:
        """Persist memories to disk."""
        try:
            with open(self._memory_path, "w", encoding="utf-8") as f:
                for mem in self._memories[-_MAX_MEMORIES:]:
                    f.write(json.dumps(mem.to_dict(), ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.debug("episodic memory save failed: %s", exc)

    # ── Storage ──────────────────────────────────────────────────────────

    def store(
        self,
        content: str,
        *,
        memory_type: str = "observation",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        source_turn: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EpisodicMemory:
        """Store a new episodic memory."""
        memory_id = f"ep_{int(time.time() * 1000)}_{len(self._memories)}"
        memory = EpisodicMemory(
            memory_id=memory_id,
            content=content[:2000],  # Bound content length
            timestamp=time.time(),
            importance=max(0.0, min(1.0, importance)),
            memory_type=memory_type,
            tags=tags or [],
            source_turn=source_turn,
            metadata=metadata or {},
        )
        self._memories.append(memory)
        self._save()
        return memory

    def store_tool_result(
        self,
        tool_name: str,
        result: str,
        *,
        success: bool = True,
        source_turn: str = "",
    ) -> EpisodicMemory:
        """Store a tool execution result as an episodic memory."""
        importance = 0.6 if success else 0.8  # Failures are more important to remember
        memory_type = "success" if success else "failure"
        content = f"Tool '{tool_name}' {'succeeded' if success else 'failed'}: {result[:500]}"
        return self.store(
            content,
            memory_type=memory_type,
            importance=importance,
            tags=[tool_name, "tool"],
            source_turn=source_turn,
        )

    def store_reflection(
        self,
        observation: str,
        *,
        root_causes: Optional[List[str]] = None,
        source_turn: str = "",
    ) -> EpisodicMemory:
        """Store a reflection/insight after observing outcomes."""
        content = f"Reflection: {observation}"
        if root_causes:
            content += f"\nRoot causes: {'; '.join(root_causes)}"
        return self.store(
            content,
            memory_type="reflection",
            importance=0.9,  # Reflections are high-importance
            tags=["reflection", "insight"],
            source_turn=source_turn,
        )

    def store_failure_insight(
        self,
        failure_evidence: str,
        *,
        root_cause: str = "",
        lesson_learned: str = "",
        source_turn: str = "",
    ) -> EpisodicMemory:
        """Store a synthesized insight from a failure (highest importance)."""
        content = f"Failure insight: {failure_evidence[:500]}"
        if root_cause:
            content += f"\nRoot cause: {root_cause}"
        if lesson_learned:
            content += f"\nLesson: {lesson_learned}"
        return self.store(
            content,
            memory_type="insight",
            importance=1.0,  # Failure insights are the most important
            tags=["failure", "insight", "lesson"],
            source_turn=source_turn,
        )

    # ── Retrieval ────────────────────────────────────────────────────────

    def _recency_score(self, memory: EpisodicMemory, now: float) -> float:
        """Exponential decay score based on age."""
        age_hours = max(0.0, (now - memory.timestamp) / 3600.0)
        # Exponential decay with half-life
        return math.exp(-0.693 * age_hours / _DECAY_HALF_LIFE_HOURS)

    def _relevance_score(self, memory: EpisodicMemory, query: str) -> float:
        """Keyword overlap score between memory content and query."""
        if not query:
            return 0.5  # Neutral when no query
        query_tokens = set(re.findall(r"[a-z0-9]{3,}", query.lower()))
        content_tokens = set(re.findall(r"[a-z0-9]{3,}", memory.content.lower()))
        tag_tokens = set(t.lower() for t in memory.tags)
        all_memory_tokens = content_tokens | tag_tokens
        if not query_tokens or not all_memory_tokens:
            return 0.1
        overlap = len(query_tokens & all_memory_tokens)
        return min(1.0, overlap / max(1, len(query_tokens)))

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        memory_type: Optional[str] = None,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Retrieve memories scored by recency × relevance × importance.

        Args:
            query: Current context/query for relevance scoring.
            top_k: Maximum memories to return.
            memory_type: Filter by memory type (observation/reflection/insight/etc.)
            min_importance: Minimum importance threshold.

        Returns:
            List of memory dicts with scores, sorted by combined score descending.
        """
        now = time.time()
        scored: List[tuple] = []

        for memory in self._memories:
            # Apply filters
            if memory_type and memory.memory_type != memory_type:
                continue
            if memory.importance < min_importance:
                continue

            # Calculate combined score
            recency = self._recency_score(memory, now)
            relevance = self._relevance_score(memory, query)
            importance = memory.importance

            combined = (
                (self._recency_weight * recency)
                * (self._relevance_weight * relevance)
                * (self._importance_weight * importance)
            )
            scored.append((combined, memory))

        # Sort by combined score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, memory in scored[:top_k]:
            entry = memory.to_dict()
            entry["score"] = round(score, 6)
            entry["recency"] = round(self._recency_score(memory, now), 4)
            entry["relevance"] = round(self._relevance_score(memory, query), 4)
            results.append(entry)
        return results

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent memories without scoring."""
        return [m.to_dict() for m in self._memories[-limit:]]

    def count(self) -> int:
        return len(self._memories)

    def stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        type_counts: Dict[str, int] = {}
        for m in self._memories:
            type_counts[m.memory_type] = type_counts.get(m.memory_type, 0) + 1
        return {
            "total": len(self._memories),
            "by_type": type_counts,
            "avg_importance": (
                sum(m.importance for m in self._memories) / len(self._memories)
                if self._memories else 0.0
            ),
        }

    def clear(self) -> int:
        """Clear all memories; returns count removed."""
        count = len(self._memories)
        self._memories.clear()
        self._save()
        return count
