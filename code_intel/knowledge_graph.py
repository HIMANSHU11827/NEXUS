"""Persistent codebase knowledge graph for structural agent context."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Any, Dict, List, Set


@dataclass
class GraphNode:
    id: str
    kind: str
    name: str
    path: str = ""
    line: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeGraph:
    root: str
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    built_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "built_at": self.built_at,
            "nodes": {node_id: asdict(node) for node_id, node in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
        }


class CodebaseKnowledgeGraph:
    """Build and query a local structural graph without importing project code."""

    EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
    EXCLUDE_DIRS = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
        "models",
        "data",
        "training_data",
        "temp_gemini_cli",
        "workspace",
        "logs",
        "scratch",
    }

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "code_graph.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def build(self, max_files: int = 5000) -> CodeGraph:
        graph = CodeGraph(root=self.root)
        edge_keys: Set[tuple[str, str, str]] = set()
        files_seen = 0

        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS and not d.endswith(".egg-info")]
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in self.EXTENSIONS:
                    continue
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, self.root).replace("\\", "/")
                file_id = self._file_id(rel_path)
                graph.nodes[file_id] = GraphNode(file_id, "file", os.path.basename(rel_path), rel_path)
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                except OSError:
                    continue

                if ext == ".py":
                    self._inspect_python(graph, edge_keys, rel_path, source)
                else:
                    self._inspect_js_like(graph, edge_keys, rel_path, source)

                files_seen += 1
                if files_seen >= max_files:
                    self._save(graph)
                    return graph

        self._save(graph)
        return graph

    def load(self) -> CodeGraph:
        if not os.path.exists(self.path):
            return CodeGraph(root=self.root)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            graph = CodeGraph(root=raw.get("root", self.root), built_at=float(raw.get("built_at", 0) or time.time()))
            graph.nodes = {node_id: GraphNode(**node) for node_id, node in raw.get("nodes", {}).items()}
            graph.edges = [GraphEdge(**edge) for edge in raw.get("edges", [])]
            return graph
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return CodeGraph(root=self.root)

    def summary(self, graph: CodeGraph | None = None, limit: int = 20) -> Dict[str, Any]:
        graph = graph or self.load()
        by_kind: Dict[str, int] = {}
        edge_kinds: Dict[str, int] = {}
        for node in graph.nodes.values():
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
        for edge in graph.edges:
            edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
        hubs = self._rank_hubs(graph)[:limit]
        return {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "by_kind": by_kind,
            "edge_kinds": edge_kinds,
            "top_hubs": hubs,
            "built_at": graph.built_at,
        }

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        graph = self.load()
        terms = [t for t in re.findall(r"[A-Za-z0-9_]+", query.lower()) if len(t) > 1]
        results = []
        for node in graph.nodes.values():
            haystack = f"{node.name} {node.path} {node.kind}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                item = asdict(node)
                item["score"] = score
                results.append(item)
        results.sort(key=lambda item: (-item["score"], item["path"], item["name"]))
        return results[:limit]

    def dependencies(self, node_or_path: str) -> List[Dict[str, Any]]:
        graph = self.load()
        node_ids = self._resolve_ids(graph, node_or_path)
        return self._edge_query(graph, node_ids, outgoing=True)

    def dependents(self, node_or_path: str) -> List[Dict[str, Any]]:
        graph = self.load()
        node_ids = self._resolve_ids(graph, node_or_path)
        return self._edge_query(graph, node_ids, outgoing=False)

    def symbol_context(self, symbol: str) -> Dict[str, Any]:
        graph = self.load()
        matches = [node for node in graph.nodes.values() if node.kind in {"function", "class", "method", "variable"} and node.name == symbol]
        return {
            "symbol": symbol,
            "matches": [asdict(node) for node in matches],
            "dependents": self.dependents(symbol),
            "dependencies": self.dependencies(symbol),
        }

    def _inspect_python(self, graph: CodeGraph, edge_keys: Set[tuple[str, str, str]], rel_path: str, source: str) -> None:
        file_id = self._file_id(rel_path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        module_aliases: Dict[str, str] = {}
        symbol_ids: Dict[str, str] = {}

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    local = alias.asname or module.split(".")[0]
                    module_aliases[local] = module
                    self._add_import_edge(graph, edge_keys, file_id, module)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self._add_import_edge(graph, edge_keys, file_id, node.module)
                for alias in node.names:
                    module_aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

        class_stack: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                node_id = self._symbol_id(rel_path, node.name, node.lineno, "class")
                graph.nodes[node_id] = GraphNode(node_id, "class", node.name, rel_path, node.lineno)
                symbol_ids[node.name] = node_id
                self._add_edge(graph, edge_keys, file_id, node_id, "defines")
                for base in node.bases:
                    base_name = self._name_from_expr(base)
                    if base_name:
                        self._add_edge(graph, edge_keys, node_id, self._external_id(base_name), "inherits")

        parents: Dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_class = self._nearest_class(node, parents)
                kind = "method" if parent_class else "function"
                name = f"{parent_class.name}.{node.name}" if parent_class else node.name
                node_id = self._symbol_id(rel_path, name, node.lineno, kind)
                graph.nodes[node_id] = GraphNode(node_id, kind, name, rel_path, node.lineno)
                symbol_ids[node.name] = node_id
                self._add_edge(graph, edge_keys, file_id, node_id, "defines")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                caller = self._nearest_function(node, parents)
                caller_id = symbol_ids.get(caller.name) if caller else file_id
                callee = self._name_from_expr(node.func)
                if callee:
                    target_id = symbol_ids.get(callee.split(".")[-1]) or self._external_id(callee)
                    self._add_edge(graph, edge_keys, caller_id, target_id, "calls")

    def _inspect_js_like(self, graph: CodeGraph, edge_keys: Set[tuple[str, str, str]], rel_path: str, source: str) -> None:
        file_id = self._file_id(rel_path)
        for match in re.finditer(r"from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]", source):
            module = match.group(1) or match.group(2)
            self._add_import_edge(graph, edge_keys, file_id, module)
        pattern = r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|(?:export\s+)?class\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="
        for match in re.finditer(pattern, source):
            name = next(group for group in match.groups() if group)
            line = source[:match.start()].count("\n") + 1
            kind = "class" if match.group(2) else "function"
            node_id = self._symbol_id(rel_path, name, line, kind)
            graph.nodes[node_id] = GraphNode(node_id, kind, name, rel_path, line)
            self._add_edge(graph, edge_keys, file_id, node_id, "defines")

    def _add_import_edge(self, graph: CodeGraph, edge_keys: Set[tuple[str, str, str]], file_id: str, module: str) -> None:
        target = self._module_to_file_id(module)
        if target not in graph.nodes:
            graph.nodes[target] = GraphNode(target, "module", module, metadata={"external": True})
        self._add_edge(graph, edge_keys, file_id, target, "imports")

    def _add_edge(self, graph: CodeGraph, edge_keys: Set[tuple[str, str, str]], source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        graph.edges.append(GraphEdge(source, target, kind))

    def _edge_query(self, graph: CodeGraph, node_ids: Set[str], outgoing: bool) -> List[Dict[str, Any]]:
        results = []
        for edge in graph.edges:
            if outgoing and edge.source not in node_ids:
                continue
            if not outgoing and edge.target not in node_ids:
                continue
            other_id = edge.target if outgoing else edge.source
            other = graph.nodes.get(other_id)
            results.append({"edge": asdict(edge), "node": asdict(other) if other else {"id": other_id}})
        return results

    def _resolve_ids(self, graph: CodeGraph, node_or_path: str) -> Set[str]:
        query = node_or_path.replace("\\", "/").strip()
        ids = {query} if query in graph.nodes else set()
        ids.update(node.id for node in graph.nodes.values() if node.path == query or node.name == query or node.id.endswith(f":{query}"))
        if not ids and "." in query and "/" not in query:
            ids.add(self._module_to_file_id(query))
        return ids

    def _rank_hubs(self, graph: CodeGraph) -> List[Dict[str, Any]]:
        degree: Dict[str, int] = {}
        for edge in graph.edges:
            degree[edge.source] = degree.get(edge.source, 0) + 1
            degree[edge.target] = degree.get(edge.target, 0) + 1
        ranked = []
        for node_id, count in sorted(degree.items(), key=lambda item: item[1], reverse=True):
            node = graph.nodes.get(node_id)
            if node:
                item = asdict(node)
                item["degree"] = count
                ranked.append(item)
        return ranked

    def _save(self, graph: CodeGraph) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(graph.to_dict(), f, indent=2)
        os.replace(temp, self.path)

    @staticmethod
    def _file_id(path: str) -> str:
        return f"file:{path}"

    @staticmethod
    def _module_to_file_id(module: str) -> str:
        return f"module:{module}"

    @staticmethod
    def _external_id(name: str) -> str:
        return f"external:{name}"

    @staticmethod
    def _symbol_id(path: str, name: str, line: int, kind: str) -> str:
        return f"{kind}:{path}:{name}:{line}"

    @staticmethod
    def _name_from_expr(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = CodebaseKnowledgeGraph._name_from_expr(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return CodebaseKnowledgeGraph._name_from_expr(node.func)
        return ""

    @staticmethod
    def _nearest_class(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> ast.ClassDef | None:
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.ClassDef):
                return parent
            parent = parents.get(parent)
        return None

    @staticmethod
    def _nearest_function(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return parent
            parent = parents.get(parent)
        return None
