"""
NATE Layer 5: Deterministic Execution Graph
Dijkstra shortest-path routing on a cost-weighted tool graph.
0 LLM calls for routing decisions. Sub-millisecond reroute on failure.
Inspired by Self-Healing Router (arXiv:2603.01548).
"""

from __future__ import annotations

import heapq
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class ToolNode:
    def __init__(self, name: str, cost: float = 1.0):
        self.name = name
        self.cost = cost
        self.failed = False

    def __repr__(self):
        return f"ToolNode({self.name}, cost={self.cost}, failed={self.failed})"


class ToolGraph:
    """Directed graph of tool nodes with weighted edges."""

    def __init__(self):
        self._nodes: Dict[str, ToolNode] = {}
        self._edges: Dict[str, List[Tuple[str, float]]] = {}

    def add_node(self, name: str, cost: float = 1.0) -> ToolNode:
        node = ToolNode(name, cost)
        self._nodes[name] = node
        if name not in self._edges:
            self._edges[name] = []
        return node

    def add_edge(self, from_name: str, to_name: str, weight: float = 1.0) -> None:
        if from_name not in self._nodes:
            self.add_node(from_name)
        if to_name not in self._nodes:
            self.add_node(to_name)
        self._edges[from_name].append((to_name, weight))

    def mark_failed(self, name: str) -> None:
        if name in self._nodes:
            self._nodes[name].failed = True

    def mark_recovered(self, name: str) -> None:
        if name in self._nodes:
            self._nodes[name].failed = False

    def shortest_path(self, start: str, goal: str) -> Tuple[Optional[List[str]], float]:
        if start not in self._nodes or goal not in self._nodes:
            return None, float("inf")
        distances: Dict[str, float] = {start: 0.0}
        previous: Dict[str, Optional[str]] = {start: None}
        pq: List[Tuple[float, str]] = [(0.0, start)]
        visited: Set[str] = set()

        while pq:
            current_dist, current = heapq.heappop(pq)
            if current in visited:
                continue
            visited.add(current)
            if current == goal:
                break
            for neighbor, edge_weight in self._edges.get(current, []):
                if self._nodes[neighbor].failed:
                    continue
                total_edge = edge_weight + self._nodes[neighbor].cost
                new_dist = current_dist + total_edge
                if new_dist < distances.get(neighbor, float("inf")):
                    distances[neighbor] = new_dist
                    previous[neighbor] = current
                    heapq.heappush(pq, (new_dist, neighbor))

        if goal not in distances or distances[goal] == float("inf"):
            return None, float("inf")

        path: List[str] = []
        node: Optional[str] = goal
        while node is not None:
            path.append(node)
            node = previous[node]
        path.reverse()
        return path, distances[goal]

    def has_path(self, start: str, goal: str) -> bool:
        path, _ = self.shortest_path(start, goal)
        return path is not None

    def __repr__(self):
        return f"ToolGraph(nodes={len(self._nodes)}, edges={sum(len(e) for e in self._edges.values())})"


class ExecutionGraph:
    """High-level execution graph with auto-reroute on failure."""

    def __init__(self):
        self.graph = ToolGraph()
        self._start: Optional[str] = None
        self._goal: Optional[str] = None
        self._node_handlers: Dict[str, Optional[Callable]] = {}

    def set_start(self, name: str) -> None:
        self.graph.add_node(name)
        self._start = name

    def set_goal(self, name: str) -> None:
        self.graph.add_node(name)
        self._goal = name

    def add_tool(self, name: str, handler: Optional[Callable] = None, cost: float = 1.0) -> None:
        self.graph.add_node(name, cost)
        self._node_handlers[name] = handler

    def add_dependency(self, from_name: str, to_name: str, weight: float = 1.0) -> None:
        self.graph.add_edge(from_name, to_name, weight)

    @property
    def start(self) -> Optional[str]:
        return self._start

    @property
    def goal(self) -> Optional[str]:
        return self._goal

    def plan(self) -> Tuple[Optional[List[str]], float]:
        if not self._start or not self._goal:
            return None, float("inf")
        return self.graph.shortest_path(self._start, self._goal)

    def reroute(self) -> Tuple[Optional[List[str]], float]:
        return self.plan()

    def execute(self, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str], List[Any]]:
        path, _ = self.plan()
        if not path:
            return False, [], ["No path found"]
        results = []
        executed = []
        i = 0
        while i < len(path):
            step = path[i]
            handler = self._node_handlers.get(step)
            if handler:
                try:
                    if context is not None:
                        result = handler(context)
                    else:
                        result = handler()
                    results.append(result)
                    executed.append(step)
                except Exception as e:
                    self.graph.mark_failed(step)
                    new_path, _ = self.reroute()
                    if new_path:
                        path = new_path
                        i = 0
                        continue
                    return False, executed, [f"{step} failed: {e}"]
            i += 1
        return True, executed, results

    def stats(self) -> Dict[str, Any]:
        return {
            "nodes": len(self.graph._nodes),
            "edges": sum(len(e) for e in self.graph._edges.values()),
            "start": self._start,
            "goal": self._goal,
            "failed_nodes": [n for n, node in self.graph._nodes.items() if node.failed],
        }
