import ast
import os
import hashlib
from typing import List, Dict, Any, Optional


class AtlasASTIndexer:
    """
    NEXUS ATLAS — AST-AWARE CONTEXTUAL INDEXER
    Processes Python files into Logical Units (Symbols) rather than raw text chunks.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.symbols: List[Dict[str, Any]] = []

    def get_source_segment(self, source: str, node: ast.AST) -> str:
        """Extract the exact source code for an AST node."""
        lines = source.splitlines()
        start = node.lineno - 1
        end = node.end_lineno
        return "\n".join(lines[start:end])

    def parse_file(self, rel_path: str) -> List[Dict[str, Any]]:
        """Parses a single file into logical symbols (Functions, Classes, Async Functions)."""
        abs_path = os.path.join(self.root, rel_path)
        symbols = []
        
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                source = f.read()
                tree = ast.parse(source)
        except Exception:
            return []

        for node in ast.walk(tree):
            symbol = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = {
                    "type": "function" if isinstance(node, ast.FunctionDef) else "async_function",
                    "name": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "content": self.get_source_segment(source, node),
                    "id": f"{rel_path}::{node.name}::{node.lineno}",
                    "parent_class": None
                }
            elif isinstance(node, ast.ClassDef):
                symbol = {
                    "type": "class",
                    "name": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "content": self.get_source_segment(source, node),
                    "id": f"{rel_path}::{node.name}::{node.lineno}",
                    "bases": [ast.dump(base) for base in node.bases]
                }

            if symbol:
                # Add a content hash for delta-indexing
                symbol["hash"] = hashlib.md5(symbol["content"].encode()).hexdigest()
                symbols.append(symbol)

        return symbols

    def scan_workspace(self, exclude: Optional[List[str]] = None) -> str:
        """Full workspace scan for symbolic logical units."""
        if exclude is None:
            exclude = [".git", "__pycache__", "node_modules", "workspace", "knowledge"]
            
        self.symbols = []
        count = 0
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in exclude]
            for f in files:
                if f.endswith(".py"):
                    rel = os.path.relpath(os.path.join(root, f), self.root).replace("\\", "/")
                    file_symbols = self.parse_file(rel)
                    self.symbols.extend(file_symbols)
                    count += 1
        
        return f"Atlas AST Scan Complete: {len(self.symbols)} logical units found across {count} files."

if __name__ == "__main__":
    indexer = AtlasASTIndexer(".")
    print(indexer.scan_workspace())
    # print(indexer.symbols[0]["content"] if indexer.symbols else "No symbols")
