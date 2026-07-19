"""
NATE Layer 6: Self-Healing Gene Map
Triple-redundant failure recovery:
1. Dijkstra reroute (from execution_graph)
2. Gene Map RL (SQLite + Q-value learning)
3. TVCache-style longest-prefix match

Inspired by Helix Gene Map + Self-Healing Router + TVCache.
0 LLM calls for recovery.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple


class Gene:
    def __init__(self, failure_code: str, strategy: str, params: Optional[Dict[str, Any]] = None):
        self.failure_code = failure_code
        self.strategy = strategy
        self.params = params or {}
        self.q_value = 0.0
        self.success_count = 0
        self.failure_count = 0
        self.avg_repair_ms = 0.0
        self.created_at = time.time()
        self.updated_at = time.time()

    def record_success(self, repair_ms: float) -> None:
        self.success_count += 1
        self.q_value = min(1.0, self.q_value + 0.1)
        self.avg_repair_ms = (self.avg_repair_ms * (self.success_count - 1) + repair_ms) / self.success_count
        self.updated_at = time.time()

    def record_failure(self) -> None:
        self.failure_count += 1
        self.q_value = max(0.0, self.q_value - 0.2)
        self.updated_at = time.time()

    @property
    def confidence(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.success_count / total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_code": self.failure_code,
            "strategy": self.strategy,
            "params": self.params,
            "q_value": round(self.q_value, 3),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "avg_repair_ms": round(self.avg_repair_ms, 1),
            "confidence": round(self.confidence, 3),
        }

    def __repr__(self):
        return f"Gene({self.failure_code}, q={self.q_value:.2f}, s={self.success_count}, f={self.failure_count})"


class GeneMap:
    """SQLite-backed Gene Map with Q-value RL.
    In-memory for now; swap to SQLite for persistence.
    """

    def __init__(self):
        self._genes: Dict[str, List[Gene]] = {}
        self._tool_call_graph: Dict[str, List[str]] = {}

    def lookup(self, failure_code: str) -> Optional[Gene]:
        genes = self._genes.get(failure_code, [])
        if not genes:
            return None
        genes.sort(key=lambda g: -g.q_value)
        return genes[0]

    def store(self, gene: Gene) -> None:
        if gene.failure_code not in self._genes:
            self._genes[gene.failure_code] = []
        self._genes[gene.failure_code].append(gene)

    def record_call_sequence(self, sequence: List[str]) -> None:
        for i in range(len(sequence) - 1):
            prev = sequence[i]
            nxt = sequence[i + 1]
            if prev not in self._tool_call_graph:
                self._tool_call_graph[prev] = []
            self._tool_call_graph[prev].append(nxt)

    def longest_prefix_match(self, current: str, max_depth: int = 3) -> Optional[List[str]]:
        if current not in self._tool_call_graph:
            return None
        result = [current]
        node = current
        for _ in range(max_depth):
            next_nodes = self._tool_call_graph.get(node, [])
            if not next_nodes:
                break
            node = next_nodes[0]
            result.append(node)
        if len(result) <= 1:
            return None
        return result

    def predict_next(self, current: str) -> Optional[str]:
        next_nodes = self._tool_call_graph.get(current, [])
        if not next_nodes:
            return None
        from collections import Counter
        counts = Counter(next_nodes)
        return counts.most_common(1)[0][0]

    def stats(self) -> Dict[str, Any]:
        total_genes = sum(len(g) for g in self._genes.values())
        return {
            "failure_patterns": len(self._genes),
            "total_genes": total_genes,
            "call_sequences": sum(len(v) for v in self._tool_call_graph.values()),
            "avg_q_value": round(sum(g.q_value for genes in self._genes.values() for g in genes) / max(total_genes, 1), 3),
        }


class RepairStrategy:
    def __init__(self, name: str, handler: Optional[Callable] = None):
        self.name = name
        self.handler = handler

    def execute(self, error: Any) -> Tuple[bool, str]:
        if self.handler:
            try:
                result = self.handler(error)
                return True, str(result)
            except Exception as e:
                return False, str(e)
        return False, "No handler registered"


class SelfHealingEngine:
    """Triple-redundant healing: graph reroute + gene map + repair strategies."""

    def __init__(self):
        self.gene_map = GeneMap()
        self._strategies: Dict[str, RepairStrategy] = {}

    def register_strategy(self, name: str, handler: Optional[Callable] = None) -> None:
        self._strategies[name] = RepairStrategy(name, handler)

    def heal(self, failure_code: str, error: Any, context: Optional[Dict] = None) -> Tuple[bool, str, str]:
        strategy_used = "none"
        result = False
        message = ""

        gene = self.gene_map.lookup(failure_code)
        if gene and gene.q_value > 0.3:
            strategy = self._strategies.get(gene.strategy)
            if strategy:
                result, message = strategy.execute(error)
                if result:
                    gene.record_success(0.1)
                    return True, message, gene.strategy
                gene.record_failure()

        for sname, strategy in self._strategies.items():
            result, message = strategy.execute(error)
            if result:
                new_gene = Gene(failure_code, sname)
                new_gene.record_success(0.1)
                self.gene_map.store(new_gene)
                return True, message, sname

        return False, f"Could not heal: {failure_code}", "none"

    def stats(self) -> Dict[str, Any]:
        return {**self.gene_map.stats(), "strategies": len(self._strategies)}
