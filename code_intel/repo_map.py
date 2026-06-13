"""Fast repository map and lightweight symbol graph."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import os
import re
from typing import Dict, Iterable, List


@dataclass
class FileNode:
    path: str
    language: str
    symbols: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    lines: int = 0


@dataclass
class RepoMap:
    root: str
    files: List[FileNode]

    def summary(self, limit: int = 80) -> str:
        lines = [f"RepoMap: {len(self.files)} source files"]
        for node in self.files[:limit]:
            symbols = ", ".join(node.symbols[:8]) if node.symbols else "-"
            imports = ", ".join(node.imports[:6]) if node.imports else "-"
            lines.append(f"- {node.path} [{node.language}, {node.lines} lines] symbols={symbols} imports={imports}")
        if len(self.files) > limit:
            lines.append(f"... {len(self.files) - limit} more files")
        return "\n".join(lines)


class RepoMapBuilder:
    """Scans source files without importing project code."""

    EXT_LANG = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".js": "javascript",
        ".jsx": "javascript-react",
        ".css": "css",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
    }

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

    def build(self, max_files: int = 5000) -> RepoMap:
        nodes: List[FileNode] = []
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS and not d.endswith(".egg-info")]
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in self.EXT_LANG:
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, self.root).replace("\\", "/")
                nodes.append(self._inspect_file(path, rel, self.EXT_LANG[ext]))
                if len(nodes) >= max_files:
                    return RepoMap(self.root, nodes)
        return RepoMap(self.root, nodes)

    def _inspect_file(self, abs_path: str, rel_path: str, language: str) -> FileNode:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            return FileNode(rel_path, language)

        lines = text.count("\n") + (1 if text else 0)
        if language == "python":
            symbols, imports = self._python_symbols(text)
        elif language.startswith(("typescript", "javascript")):
            symbols, imports = self._js_symbols(text)
        else:
            symbols, imports = [], []
        return FileNode(rel_path, language, symbols, imports, lines)

    def _python_symbols(self, text: str) -> tuple[List[str], List[str]]:
        symbols: List[str] = []
        imports: List[str] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return symbols, imports
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return symbols, sorted(set(imports))

    def _js_symbols(self, text: str) -> tuple[List[str], List[str]]:
        symbols = re.findall(r"(?:function|class)\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", text)
        flat_symbols = [a or b for a, b in symbols if a or b]
        imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]", text)
        flat_imports = [a or b for a, b in imports if a or b]
        return flat_symbols, sorted(set(flat_imports))
