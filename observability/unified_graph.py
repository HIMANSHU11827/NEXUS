from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GraphSnapshot:
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


class UnifiedNexusGraph:
    """Compact graph summary for GUI audit widgets."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.graphify_path = os.path.join(root, ".nexus", "graphify-out", "graph.json")
        self.events_dir = os.path.join(root, ".nexus", "workspace", "work_events")

    def load(self) -> GraphSnapshot:
        if not os.path.exists(self.graphify_path):
            return GraphSnapshot(nodes=[], edges=[])
        try:
            with open(self.graphify_path, "r", encoding="utf-8", errors="ignore") as handle:
                data = json.load(handle)
            nodes = data.get("nodes", []) if isinstance(data, dict) else []
            edges = data.get("edges", []) if isinstance(data, dict) else []
            return GraphSnapshot(nodes=list(nodes), edges=list(edges))
        except (OSError, json.JSONDecodeError):
            return GraphSnapshot(nodes=[], edges=[])

    def build(self, event_limit: int = 100, include_code: bool = False) -> GraphSnapshot:
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        def add_node(node_id: str, kind: str, label: str) -> None:
            nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label})

        add_node("nexus", "system", "NEXUS AI")
        if os.path.isdir(self.events_dir):
            seen = 0
            for name in os.listdir(self.events_dir):
                if seen >= event_limit:
                    break
                if not name.endswith(".jsonl"):
                    continue
                session_id = name[:-6]
                add_node(f"session:{session_id}", "session", session_id)
                edges.append({"source": "nexus", "target": f"session:{session_id}", "type": "has_session"})
                path = os.path.join(self.events_dir, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        for line in handle:
                            if seen >= event_limit:
                                break
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            kind = str(event.get("kind") or event.get("type") or "tool")
                            action = str(event.get("action") or event.get("title") or kind)
                            node_id = f"event:{event.get('id') or seen}"
                            add_node(node_id, kind, action)
                            edges.append({"source": f"session:{session_id}", "target": node_id, "type": "emitted"})
                            seen += 1
                except OSError:
                    continue
        if include_code:
            for rel in ("apps/web/api.py", "src/nexus/main_agent/core.py", "apps/web/src/App.tsx"):
                if os.path.exists(os.path.join(self.root, rel)):
                    add_node(f"file:{rel}", "file", rel)
                    edges.append({"source": "nexus", "target": f"file:{rel}", "type": "contains"})
        return GraphSnapshot(nodes=list(nodes.values()), edges=edges)

    def summary(self, snapshot: GraphSnapshot) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        for node in snapshot.nodes:
            kind = str(node.get("kind") or "unknown")
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "nodes": len(snapshot.nodes),
            "edges": len(snapshot.edges),
            "by_kind": by_kind,
        }
