"""Adaptive memory graph with ranking, contradiction repair, and cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class MemoryNode:
    id: str
    layer: str
    text: str
    importance: float
    confidence: float
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    active: bool = True


class AdaptiveMemoryGraph:
    """Small persistent graph store for project/personality/failure memory."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "memory_graph.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.nodes: Dict[str, MemoryNode] = {}
        self._load()

    def add(
        self,
        text: str,
        layer: str = "project",
        importance: float = 0.5,
        confidence: float = 0.8,
        tags: Optional[List[str]] = None,
        links: Optional[List[str]] = None,
    ) -> MemoryNode:
        normalized = self._normalize(text)
        node_id = f"{layer}:{abs(hash(normalized))}"
        existing = self.nodes.get(node_id)
        now = time.time()
        if existing:
            existing.importance = max(existing.importance, importance)
            existing.confidence = max(existing.confidence, confidence)
            existing.tags = sorted(set(existing.tags + (tags or [])))
            existing.links = sorted(set(existing.links + (links or [])))
            existing.updated_at = now
            existing.active = True
            self._save()
            return existing

        node = MemoryNode(
            id=node_id,
            layer=layer,
            text=text.strip(),
            importance=max(0.0, min(1.0, importance)),
            confidence=max(0.0, min(1.0, confidence)),
            tags=tags or self._auto_tags(text),
            links=links or [],
        )
        self.nodes[node.id] = node
        self.repair_contradictions(node)
        self._save()
        return node

    def recall(self, query: str, layer: Optional[str] = None, limit: int = 8) -> List[MemoryNode]:
        q_terms = set(self._terms(query))
        scored: List[tuple[float, MemoryNode]] = []
        now = time.time()
        for node in self.nodes.values():
            if not node.active:
                continue
            if layer and node.layer != layer:
                continue
            terms = set(self._terms(node.text + " " + " ".join(node.tags)))
            overlap = len(q_terms & terms)
            if q_terms and overlap == 0:
                continue
            age_days = max((now - node.updated_at) / 86400, 0.0)
            recency = 1.0 / (1.0 + age_days / 30.0)
            score = overlap + node.importance * 2 + node.confidence + recency
            scored.append((score, node))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [node for _, node in scored[:limit]]

    def compressed_packet(self, query: str, limit: int = 8) -> Dict[str, Any]:
        nodes = self.recall(query, limit=limit)
        return {
            "type": "memory_packet",
            "query": query,
            "pointers": [node.id for node in nodes],
            "facts": [node.text for node in nodes],
            "generated_at": time.time(),
        }

    def repair_contradictions(self, new_node: MemoryNode) -> int:
        """Deactivate weaker opposite-polarity nodes with similar tags."""
        new_terms = set(self._terms(new_node.text))
        new_polarity = self._polarity(new_node.text)
        if new_polarity == 0:
            return 0
        changed = 0
        for node in self.nodes.values():
            if node.id == new_node.id or not node.active or node.layer != new_node.layer:
                continue
            overlap = len(new_terms & set(self._terms(node.text)))
            if overlap < 3:
                continue
            if self._polarity(node.text) == -new_polarity and new_node.confidence >= node.confidence:
                node.active = False
                node.updated_at = time.time()
                changed += 1
        return changed

    def cleanup(self, min_importance: float = 0.15, max_inactive: int = 500) -> int:
        before = len(self.nodes)
        active = {k: v for k, v in self.nodes.items() if v.active and v.importance >= min_importance}
        inactive = [v for v in self.nodes.values() if not v.active]
        inactive.sort(key=lambda n: n.updated_at, reverse=True)
        for node in inactive[:max_inactive]:
            active[node.id] = node
        self.nodes = active
        self._save()
        return before - len(self.nodes)

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.nodes = {k: MemoryNode(**v) for k, v in raw.items()}
        except Exception:
            self.nodes = {}

    def _save(self) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.nodes.items()}, f, indent=2)
        os.replace(temp, self.path)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _terms(text: str) -> List[str]:
        return [t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(t) > 2]

    def _auto_tags(self, text: str) -> List[str]:
        terms = self._terms(text)
        return sorted(set(terms[:12]))

    @staticmethod
    def _polarity(text: str) -> int:
        lowered = text.lower()
        if any(w in lowered for w in ["not ", "never", "disable", "broken", "failed", "unsafe"]):
            return -1
        if any(w in lowered for w in ["enable", "works", "passed", "safe", "preferred"]):
            return 1
        return 0
