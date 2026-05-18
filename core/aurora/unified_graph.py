"""Unified NEXUS graph over code, memory, evidence, sessions, and metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import time
from typing import Any, Dict, Iterable, List, Set


@dataclass
class UnifiedNode:
    id: str
    kind: str
    label: str
    source: str
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnifiedEdge:
    source: str
    target: str
    kind: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedGraph:
    root: str
    nodes: Dict[str, UnifiedNode] = field(default_factory=dict)
    edges: List[UnifiedEdge] = field(default_factory=list)
    built_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "built_at": self.built_at,
            "nodes": {node_id: asdict(node) for node_id, node in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
        }


class UnifiedNexusGraph:
    """Consolidates scattered NEXUS graph/log stores into one queryable index."""

    STORES = {
        "code_graph": "workspace/code_graph.json",
        "memory_graph": "workspace/memory_graph.json",
        "evidence_ledger": "workspace/evidence_ledger.json",
        "mission_replay": "workspace/mission_replay.jsonl",
        "tool_economy": "workspace/tool_economy.json",
        "benchmark_history": "workspace/benchmark_history.jsonl",
        "failure_vaccines": "workspace/failure_vaccines.jsonl",
        "self_improvement": "workspace/self_improvement.json",
        "todos": "workspace/todos.json",
        "sessions": "logs/sessions",
        "swarm_logs": "logs/swarm",
        "agent_context": "AGENTS.md",
    }

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "unified_graph.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def build(self, event_limit: int = 1000, include_code: bool = True) -> UnifiedGraph:
        graph = UnifiedGraph(root=self.root)
        edge_keys: Set[tuple[str, str, str]] = set()
        for store, rel_path in self.STORES.items():
            self._add_node(
                graph,
                f"store:{store}",
                "store",
                store,
                "unified_graph",
                metadata={"path": rel_path, "exists": os.path.exists(os.path.join(self.root, rel_path))},
            )

        if include_code:
            self._ingest_code_graph(graph, edge_keys)
        self._ingest_memory(graph, edge_keys)
        self._ingest_evidence(graph, edge_keys)
        self._ingest_mission_replay(graph, edge_keys, event_limit=event_limit)
        self._ingest_tool_economy(graph, edge_keys)
        self._ingest_benchmarks(graph, edge_keys, event_limit=event_limit)
        self._ingest_self_improvement(graph, edge_keys)
        self._ingest_failure_vaccines(graph, edge_keys, event_limit=event_limit)
        self._ingest_todos(graph, edge_keys)
        self._ingest_sessions(graph, edge_keys, event_limit=event_limit)
        self._ingest_swarm_logs(graph, edge_keys, event_limit=event_limit)
        self._ingest_agent_context_files(graph, edge_keys)
        self._save(graph)
        return graph

    def load(self) -> UnifiedGraph:
        if not os.path.exists(self.path):
            return UnifiedGraph(root=self.root)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            graph = UnifiedGraph(root=raw.get("root", self.root), built_at=float(raw.get("built_at", 0) or time.time()))
            graph.nodes = {node_id: UnifiedNode(**node) for node_id, node in raw.get("nodes", {}).items()}
            graph.edges = [UnifiedEdge(**edge) for edge in raw.get("edges", [])]
            return graph
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return UnifiedGraph(root=self.root)

    def summary(self, graph: UnifiedGraph | None = None) -> Dict[str, Any]:
        graph = graph or self.load()
        by_kind: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        edge_kinds: Dict[str, int] = {}
        for node in graph.nodes.values():
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
            by_source[node.source] = by_source.get(node.source, 0) + 1
        for edge in graph.edges:
            edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
        return {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "by_kind": by_kind,
            "by_source": by_source,
            "edge_kinds": edge_kinds,
            "built_at": graph.built_at,
            "path": self.path,
        }

    def search(self, query: str, kinds: Iterable[str] | None = None, limit: int = 25) -> List[Dict[str, Any]]:
        graph = self.load()
        allowed = set(kinds or [])
        terms = [term.lower() for term in str(query or "").split() if term.strip()]
        results: List[Dict[str, Any]] = []
        for node in graph.nodes.values():
            if allowed and node.kind not in allowed:
                continue
            haystack = " ".join(
                [
                    node.id,
                    node.kind,
                    node.label,
                    node.source,
                    json.dumps(node.metadata, sort_keys=True, default=str)[:2000],
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score or not terms:
                item = asdict(node)
                item["score"] = score
                results.append(item)
        results.sort(key=lambda item: (-item["score"], -float(item.get("timestamp", 0) or 0), item["id"]))
        return results[:limit]

    def neighborhood(self, node_id: str, depth: int = 1, limit: int = 50) -> Dict[str, Any]:
        graph = self.load()
        if node_id not in graph.nodes:
            return {"node": node_id, "nodes": [], "edges": []}
        seen = {node_id}
        frontier = {node_id}
        selected_edges: List[UnifiedEdge] = []
        for _ in range(max(1, min(depth, 4))):
            next_frontier: Set[str] = set()
            for edge in graph.edges:
                if edge.source in frontier or edge.target in frontier:
                    selected_edges.append(edge)
                    other = edge.target if edge.source in frontier else edge.source
                    if other not in seen:
                        seen.add(other)
                        next_frontier.add(other)
                if len(seen) >= limit:
                    break
            frontier = next_frontier
            if not frontier or len(seen) >= limit:
                break
        return {
            "node": node_id,
            "nodes": [asdict(graph.nodes[node]) for node in list(seen)[:limit] if node in graph.nodes],
            "edges": [asdict(edge) for edge in selected_edges[:limit]],
        }

    def close_session(self, mission_id: str = "default", note: str = "") -> Dict[str, Any]:
        from core.aurora.mission_replay import MissionReplay

        MissionReplay(self.root).record("session_closed", {"note": note or "session closed into unified graph"}, mission_id=mission_id)
        graph = self.build()
        return {"mission_id": mission_id, "closed": True, "summary": self.summary(graph)}

    def _ingest_code_graph(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/code_graph.json", default={})
        nodes = raw.get("nodes", {}) if isinstance(raw, dict) else {}
        edges = raw.get("edges", []) if isinstance(raw, dict) else []
        for node_id, node in nodes.items():
            metadata = dict(node.get("metadata", {})) if isinstance(node.get("metadata", {}), dict) else {}
            metadata.update({"path": node.get("path", ""), "line": node.get("line", 0)})
            unified_id = f"code:{node_id}"
            self._add_node(graph, unified_id, f"code_{node.get('kind', 'node')}", node.get("name") or node_id, "code_graph", metadata=metadata)
            self._add_edge(graph, edge_keys, "store:code_graph", unified_id, "contains")
        for edge in edges:
            source = f"code:{edge.get('source', '')}"
            target = f"code:{edge.get('target', '')}"
            if source in graph.nodes and target in graph.nodes:
                self._add_edge(graph, edge_keys, source, target, f"code_{edge.get('kind', 'rel')}", metadata=edge.get("metadata", {}))

    def _ingest_memory(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/memory_graph.json", default={})
        for memory_id, node in (raw or {}).items():
            unified_id = f"memory:{memory_id}"
            self._add_node(
                graph,
                unified_id,
                "memory",
                node.get("text", memory_id)[:120],
                "memory_graph",
                timestamp=float(node.get("updated_at", 0) or 0),
                metadata={k: node.get(k) for k in ["layer", "importance", "confidence", "tags", "active"]},
            )
            self._add_edge(graph, edge_keys, "store:memory_graph", unified_id, "contains")
            for link in node.get("links", []) or []:
                link_id = f"memory_ref:{link}"
                self._add_node(graph, link_id, "memory_ref", str(link), "memory_graph")
                self._add_edge(graph, edge_keys, unified_id, link_id, "links")

    def _ingest_evidence(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/evidence_ledger.json", default={})
        for evidence_id, record in (raw or {}).items():
            unified_id = f"evidence:{evidence_id}"
            self._add_node(
                graph,
                unified_id,
                "evidence",
                record.get("claim", evidence_id),
                "evidence_ledger",
                timestamp=float(record.get("updated_at", 0) or 0),
                metadata={k: record.get(k) for k in ["status", "confidence", "mission_id"]},
            )
            self._add_edge(graph, edge_keys, "store:evidence_ledger", unified_id, "contains")
            mission_id = f"mission:{record.get('mission_id', 'default')}"
            self._add_node(graph, mission_id, "mission", record.get("mission_id", "default"), "mission_replay")
            self._add_edge(graph, edge_keys, unified_id, mission_id, "supports_mission")
            for index, item in enumerate(record.get("evidence", []) or []):
                item_id = f"evidence_item:{evidence_id}:{index}"
                self._add_node(graph, item_id, "evidence_item", item.get("source", "evidence"), "evidence_ledger", metadata=item)
                self._add_edge(graph, edge_keys, unified_id, item_id, "has_evidence")

    def _ingest_mission_replay(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], event_limit: int) -> None:
        for index, event in enumerate(self._read_jsonl_tail("workspace/mission_replay.jsonl", event_limit)):
            timestamp = float(event.get("timestamp", 0) or 0)
            event_id = f"event:{int(timestamp * 1000)}:{index}"
            event_type = event.get("event_type", "event")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            mission_id = f"mission:{event.get('mission_id', 'default')}"
            label = f"{event_type}:{data.get('tool', data.get('command', ''))}".strip(":")
            self._add_node(graph, mission_id, "mission", event.get("mission_id", "default"), "mission_replay")
            self._add_node(graph, event_id, "event", label, "mission_replay", timestamp=timestamp, metadata={"event_type": event_type, "data": data})
            self._add_edge(graph, edge_keys, "store:mission_replay", event_id, "contains")
            self._add_edge(graph, edge_keys, mission_id, event_id, "has_event")
            tool = data.get("tool")
            if tool:
                tool_id = f"tool:{tool}"
                self._add_node(graph, tool_id, "tool", str(tool), "tool_economy")
                self._add_edge(graph, edge_keys, event_id, tool_id, "used_tool")

    def _ingest_tool_economy(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/tool_economy.json", default={})
        for tool_name, stats in (raw or {}).items():
            tool_id = f"tool:{tool_name}"
            self._add_node(graph, tool_id, "tool", str(tool_name), "tool_economy", timestamp=float(stats.get("last_used", 0) or 0), metadata=stats)
            self._add_edge(graph, edge_keys, "store:tool_economy", tool_id, "contains")

    def _ingest_benchmarks(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], event_limit: int) -> None:
        for index, run in enumerate(self._read_jsonl_tail("workspace/benchmark_history.jsonl", max(10, min(event_limit, 100)))):
            timestamp = float(run.get("timestamp", 0) or 0)
            run_id = f"benchmark:{int(timestamp * 1000)}:{index}"
            self._add_node(
                graph,
                run_id,
                "benchmark",
                f"{run.get('score', 0)}/{run.get('total', 0)}",
                "benchmark_history",
                timestamp=timestamp,
                metadata={k: run.get(k) for k in ["suite_version", "score", "total", "pass_rate"]},
            )
            self._add_edge(graph, edge_keys, "store:benchmark_history", run_id, "contains")

    def _ingest_failure_vaccines(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], event_limit: int) -> None:
        for record in self._read_jsonl_tail("workspace/failure_vaccines.jsonl", event_limit):
            vaccine_id = f"vaccine:{record.get('id', self._digest(record))}"
            self._add_node(
                graph,
                vaccine_id,
                "failure_vaccine",
                record.get("task") or record.get("error") or vaccine_id,
                "failure_vaccines",
                timestamp=float(record.get("created_at", 0) or 0),
                metadata={k: record.get(k) for k in ["tool", "error", "severity", "status", "affected_files", "test_commands"]},
            )
            self._add_edge(graph, edge_keys, "store:failure_vaccines", vaccine_id, "contains")
            for ref_key, edge_kind in [("memory_node_id", "links_memory"), ("strategy_id", "links_strategy")]:
                ref = record.get(ref_key)
                if ref:
                    ref_id = f"memory:{ref}" if ref_key == "memory_node_id" else f"strategy:{ref}"
                    self._add_node(graph, ref_id, "reference", str(ref), "failure_vaccines")
                    self._add_edge(graph, edge_keys, vaccine_id, ref_id, edge_kind)
            for path in record.get("affected_files", []) or []:
                code_id = f"code:file:{str(path).replace(os.sep, '/')}"
                if code_id in graph.nodes:
                    self._add_edge(graph, edge_keys, vaccine_id, code_id, "affects_code")

    def _ingest_self_improvement(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/self_improvement.json", default={})
        for strategy_id, strategy in (raw or {}).items():
            unified_id = f"strategy:{strategy_id}"
            self._add_node(
                graph,
                unified_id,
                "strategy",
                strategy.get("strategy") or strategy.get("trigger") or strategy_id,
                "self_improvement",
                timestamp=float(strategy.get("updated_at", 0) or 0),
                metadata={k: strategy.get(k) for k in ["trigger", "wins", "failures", "evidence"]},
            )
            self._add_edge(graph, edge_keys, "store:self_improvement", unified_id, "contains")

    def _ingest_todos(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        raw = self._read_json("workspace/todos.json", default=[])
        todos = raw if isinstance(raw, list) else raw.get("todos", []) if isinstance(raw, dict) else []
        for item in todos:
            todo_id = f"todo:{item.get('id', self._digest(item))}"
            self._add_node(
                graph,
                todo_id,
                "todo",
                item.get("content") or item.get("title") or todo_id,
                "todos",
                timestamp=float(item.get("created", item.get("created_at", 0)) or 0),
                metadata={k: item.get(k) for k in item.keys() if k not in {"content", "title"}},
            )
            self._add_edge(graph, edge_keys, "store:todos", todo_id, "contains")

    def _ingest_sessions(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], event_limit: int) -> None:
        sessions_dir = os.path.join(self.root, "logs", "sessions")
        if not os.path.isdir(sessions_dir):
            return
        for filename in sorted(os.listdir(sessions_dir))[-50:]:
            if not filename.endswith(".json"):
                continue
            rel_path = f"logs/sessions/{filename}"
            raw = self._read_json(rel_path, default=[])
            messages = raw if isinstance(raw, list) else raw.get("messages", []) if isinstance(raw, dict) else []
            session_name = os.path.splitext(filename)[0]
            session_id = f"session:{session_name}"
            path = os.path.join(self.root, rel_path)
            self._add_node(
                graph,
                session_id,
                "session",
                session_name,
                "sessions",
                timestamp=os.path.getmtime(path) if os.path.exists(path) else 0.0,
                metadata={"path": rel_path, "messages": len(messages)},
            )
            self._add_edge(graph, edge_keys, "store:sessions", session_id, "contains")
            for index, message in enumerate(messages[-max(0, min(event_limit, 200)):]):
                content = str(message.get("content", "")) if isinstance(message, dict) else str(message)
                role = message.get("role", "message") if isinstance(message, dict) else "message"
                message_id = f"session_msg:{session_name}:{index}:{self._digest(content)}"
                self._add_node(
                    graph,
                    message_id,
                    "session_message",
                    content[:160],
                    "sessions",
                    metadata={"role": role, "path": rel_path, "index": index},
                )
                self._add_edge(graph, edge_keys, session_id, message_id, "has_message")

    def _ingest_swarm_logs(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], event_limit: int) -> None:
        swarm_dir = os.path.join(self.root, "logs", "swarm")
        if not os.path.isdir(swarm_dir):
            return
        for root, _, files in os.walk(swarm_dir):
            for filename in sorted(files)[:200]:
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, self.root).replace("\\", "/")
                log_id = f"swarm_log:{self._digest(rel_path)}"
                self._add_node(
                    graph,
                    log_id,
                    "swarm_log",
                    filename,
                    "swarm_logs",
                    timestamp=os.path.getmtime(abs_path),
                    metadata={"path": rel_path, "bytes": os.path.getsize(abs_path)},
                )
                self._add_edge(graph, edge_keys, "store:swarm_logs", log_id, "contains")
                if filename.endswith(".jsonl"):
                    for index, event in enumerate(self._read_jsonl_tail(rel_path, max(0, min(event_limit, 100)))):
                        event_id = f"swarm_event:{self._digest(rel_path)}:{index}"
                        self._add_node(graph, event_id, "swarm_event", event.get("type", event.get("event", "swarm_event")), "swarm_logs", metadata=event)
                        self._add_edge(graph, edge_keys, log_id, event_id, "has_event")
                if filename == "hive_manifest.json":
                    manifest = self._read_json(rel_path, default={})
                    for item in manifest.get("contracts", []) if isinstance(manifest, dict) else []:
                        contract_id = f"swarm_contract:{item.get('id', self._digest(item))}"
                        self._add_node(graph, contract_id, "swarm_contract", item.get("objective", item.get("role", "contract")), "swarm_logs", metadata=item)
                        self._add_edge(graph, edge_keys, log_id, contract_id, "has_contract")
                    for item in manifest.get("handoffs", []) if isinstance(manifest, dict) else []:
                        handoff_id = f"swarm_handoff:{item.get('id', self._digest(item))}"
                        self._add_node(graph, handoff_id, "swarm_handoff", item.get("objective", item.get("role", "handoff")), "swarm_logs", metadata=item)
                        self._add_edge(graph, edge_keys, log_id, handoff_id, "has_handoff")

    def _ingest_agent_context_files(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]]) -> None:
        for filename in ["AGENTS.md", "CLAUDE.md"]:
            path = os.path.join(self.root, filename)
            if not os.path.exists(path):
                continue
            preview = self._read_text_head(filename, limit=1200)
            node_id = f"agent_context:{filename}"
            self._add_node(
                graph,
                node_id,
                "agent_context",
                filename,
                "agent_context",
                timestamp=os.path.getmtime(path),
                metadata={"path": filename, "bytes": os.path.getsize(path), "preview": preview},
            )
            self._add_edge(graph, edge_keys, "store:agent_context", node_id, "contains")

    def _add_node(self, graph: UnifiedGraph, node_id: str, kind: str, label: str, source: str, timestamp: float = 0.0, metadata: Dict[str, Any] | None = None) -> None:
        existing = graph.nodes.get(node_id)
        if existing:
            existing.metadata.update(metadata or {})
            existing.timestamp = max(existing.timestamp, timestamp or 0.0)
            return
        graph.nodes[node_id] = UnifiedNode(node_id, kind, str(label)[:500], source, timestamp, metadata or {})

    def _add_edge(self, graph: UnifiedGraph, edge_keys: Set[tuple[str, str, str]], source: str, target: str, kind: str, metadata: Dict[str, Any] | None = None) -> None:
        key = (source, target, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        graph.edges.append(UnifiedEdge(source, target, kind, metadata or {}))

    def _save(self, graph: UnifiedGraph) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(graph.to_dict(), f, indent=2)
        os.replace(temp, self.path)

    def _read_json(self, rel_path: str, default: Any) -> Any:
        path = os.path.join(self.root, rel_path)
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    def _read_jsonl_tail(self, rel_path: str, limit: int) -> List[Dict[str, Any]]:
        path = os.path.join(self.root, rel_path)
        if not os.path.exists(path):
            return []
        records: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-max(0, limit):]
            for line in lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
        except OSError:
            return []
        return records

    def _read_text_head(self, rel_path: str, limit: int = 2000) -> str:
        path = os.path.join(self.root, rel_path)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(limit)
        except OSError:
            return ""

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
