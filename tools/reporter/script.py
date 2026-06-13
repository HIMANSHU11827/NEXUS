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
        # If DB exists, verify it's readable SQLite before reusing
        if os.path.exists(self._db_path):
            try:
                conn = sqlite3.connect(self._db_path)
                conn.execute("SELECT COUNT(*) FROM symbols LIMIT 1")
                conn.execute("PRAGMA integrity_check").fetchall()
                conn.close()
                # DB is valid — nothing more to do
                return
            except sqlite3.DatabaseError:
                pass
            # If we get here, the DB is corrupt — delete so it regenerates
            try:
                conn.close()
            except Exception:
                pass
            os.remove(self._db_path)
        # Create fresh DB
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

    def deep_dependency_scan(self, target_file: str) -> str:
        """
        [ARCHITECTURAL_ANALYSIS]: Maps cross-file dependencies for a target.
        Finds all files that import symbols from the target_file.
        """
        target_rel = os.path.relpath(os.path.abspath(target_file), self.root).replace("\\", "/")
        
        # 1. Find all symbols defined in target_file
        conn = sqlite3.connect(self._db_path)
        symbols = [r[0] for r in conn.execute("SELECT name FROM symbols WHERE file = ?", (target_rel,)).fetchall()]
        
        if not symbols:
            return f"No symbols found in {target_rel} to track."

        # 2. Scan other files for imports of these symbols
        impacted_files = {}
        for root, _, files in os.walk(self.root):
            for f in files:
                if f.endswith(".py") and f != os.path.basename(target_file):
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.root).replace("\\", "/")
                    try:
                        with open(path, "r", encoding="utf-8") as f_obj:
                            content = f_obj.read()
                            # Check for 'from [module] import [symbol]' or 'import [module]'
                            for sym in symbols:
                                if f"import {sym}" in content or sym in content: # Heuristic for now
                                    impacted_files.setdefault(rel, []).append(sym)
                    except Exception:
                        continue
        
        if not impacted_files:
            return f"No direct external dependencies found for {target_rel}."
            
        report = [f"[IMPACT_ANALYSIS] for {target_rel}:"]
        for f, syms in impacted_files.items():
            report.append(f"- {f} (uses: {', '.join(syms)})")
            
        return "\n".join(report)

    def find_all_calls(self, symbol_name: str) -> List[Tuple[str, int]]:
        """Finds all locations where a symbol is called in the workspace."""
        # This would use ripgrep/grep for speed in a production system.
        # For now, we provide a functional implementation for the agent.
        results = []
        for root, _, files in os.walk(self.root):
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    with open(path, "r", encoding="utf-8") as f_obj:
                        for i, line in enumerate(f_obj, 1):
                            if f"{symbol_name}(" in line:
                                rel = os.path.relpath(path, self.root).replace("\\", "/")
                                results.append((rel, i))
        return results


if __name__ == "__main__":
    lsp = NexusLSPTool()
    # print(lsp.index_workspace())
    # print(lsp.find_symbol("NexusArchitect"))
