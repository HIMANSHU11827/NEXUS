import ast
import os
import sqlite3
import json
from typing import List, Dict, Any, Tuple


class NexusLSPTool:
    """
    Language Server Protocol (LSP) engine for global symbol resolution, 
    workspace indexing, and cross-file architectural analysis.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self._db_path = os.path.join(self.root, "knowledge", "_nexus_symbol_map.db")
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS symbols (name TEXT, type TEXT, file TEXT, line INTEGER, docstring TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON symbols(name)")
        conn.close()

    def index_workspace(self) -> str:
        """Deep-scans the repository and builds the global symbol index."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM symbols")
        count = 0
        for root, _, files in os.walk(self.root):
            if any(
                x in root for x in [".git", "__pycache__", "node_modules", "workspace"]
            ):
                continue
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.root)
                    count += self._index_file(conn, path, rel)
        conn.commit()
        conn.close()
        return f"NEXUS LSP Index Updated: {count} symbols indexed across workspace."

    def index_file(self, file_path: str) -> str:
        """Surgical single-file symbol update."""
        abs_path = (
            os.path.join(self.root, file_path)
            if not os.path.isabs(file_path)
            else file_path
        )
        if not os.path.exists(abs_path):
            return "File not found."

        conn = sqlite3.connect(self._db_path)
        rel_path = os.path.relpath(abs_path, self.root).replace("\\", "/")
        conn.execute("DELETE FROM symbols WHERE file = ?", (rel_path,))
        count = self._index_file(conn, abs_path, rel_path)
        conn.commit()
        conn.close()
        return f"Indexed {count} symbols in {rel_path}"

    def _index_file(self, conn, abs_path: str, rel_path: str) -> int:
        count = 0
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    doc = ast.get_docstring(node) or ""
                    ntype = "CLASS" if isinstance(node, ast.ClassDef) else "FUNC"
                    conn.execute(
                        "INSERT INTO symbols VALUES (?, ?, ?, ?, ?)",
                        (node.name, ntype, rel_path, node.lineno, doc),
                    )
                    count += 1
        except (SyntaxError, OSError, UnicodeDecodeError):
            pass
        return count

    def find_symbol(self, name: str) -> str:
        """Resolves a symbol name to its file location and type."""
        conn = sqlite3.connect(self._db_path)
        res = conn.execute(
            "SELECT type, file, line, docstring FROM symbols WHERE name = ?", (name,)
        ).fetchall()
        conn.close()
        if not res:
            return f"[ERROR]: Symbol '{name}' not found."

        parts = []
        for r in res:
            parts.append(
                f"{r[0]} '{name}' | Source: {r[1]}:{r[2]}\nDoc: {r[3][:100]}..."
            )
        return "\n---\n".join(parts)

    def check_syntax(self, file_path: str) -> str:
        """Standard AST syntax check."""
        abs_path = os.path.join(self.root, file_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                ast.parse(f.read())
            return f"✅ Syntax OK for {file_path}."
        except SyntaxError as e:
            return f"❌ SYNTAX_ERROR in {file_path}: {e.msg} at line {e.lineno}"
        except (OSError, IOError):
            return f"❌ FILE_NOT_FOUND: {file_path}"

    def check_file(self, file_path: str) -> str:
        """Alias for check_syntax for coordinator compatibility."""
        return self.check_syntax(file_path)


if __name__ == "__main__":
    lsp = NexusLSPTool()
    # print(lsp.index_workspace())
    # print(lsp.find_symbol("NexusArchitect"))
