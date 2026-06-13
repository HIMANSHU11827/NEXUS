"""
NEXUS SESSION SEARCH TOOL — Search past conversations
Like Hermes session_search: FTS5-backed retrieval over message store.
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class SessionSearchTool(BaseTool):
    """Search past sessions using full-text search on stored conversations."""
    name = "session_search"
    description = "Search past conversations for relevant context, decisions, and code references. Uses FTS5 full-text search."
    aliases = ["history_search", "past_sessions", "recall_session"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        # Look for session DBs in common locations
        self._find_session_db()

    def _find_session_db(self):
        """Find the session database file."""
        candidates = [
            os.path.join(self.root, "workspace", "sessions.db"),
            os.path.join(self.root, "knowledge", "sessions.db"),
            os.path.join(self.root, "data", "sessions.db"),
            os.path.expanduser("~/.hermes/state.db"),
        ]
        self.db_path = None
        for path in candidates:
            if os.path.exists(path):
                self.db_path = path
                break

    def call(self, query: str = "", limit: int = 5, session_id: str = "") -> ToolResult:
        try:
            if not query and not session_id:
                return self._browse_recent(limit)
            
            if not self.db_path:
                return ToolResult(data="No session database found. NEXUS sessions are stored in workspace/sessions/ as JSON files. Try: `grep` in the sessions directory.")

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            results = []

            if session_id:
                # Get all messages for a specific session
                cur = conn.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY created_at LIMIT ?",
                    (session_id, limit * 10)
                )
                for row in cur.fetchall():
                    results.append(dict(row))
            else:
                # FTS5 search across all sessions
                try:
                    cur = conn.execute(
                        """SELECT s.id as session_id, s.title, m.role, m.content, m.created_at
                           FROM messages m 
                           JOIN sessions s ON m.session_id = s.id
                           WHERE m.content MATCH ? 
                           ORDER BY m.created_at DESC LIMIT ?""",
                        (query, limit * 5)
                    )
                    for row in cur.fetchall():
                        results.append(dict(row))
                except sqlite3.OperationalError:
                    # Fallback to LIKE search if FTS not available
                    cur = conn.execute(
                        """SELECT s.id as session_id, s.title, m.role, m.content, m.created_at
                           FROM messages m 
                           JOIN sessions s ON m.session_id = s.id
                           WHERE m.content LIKE ? 
                           ORDER BY m.created_at DESC LIMIT ?""",
                        (f"%{query}%", limit * 5)
                    )
                    for row in cur.fetchall():
                        results.append(dict(row))

            conn.close()

            if not results:
                # Fallback: search the workspace/sessions/ JSON files
                return self._search_json_sessions(query, limit)

            output = f"### [SESSION SEARCH] Query: {query or 'recent'}\n\n"
            for r in results[:limit]:
                title = r.get("title", r.get("session_id", "unknown"))
                role = r.get("role", "user")
                content = str(r.get("content", ""))[:300]
                ts = r.get("created_at", "")
                output += f"[{ts}] {title} | {role}\n  {content}\n\n"

            return ToolResult(data=output)

        except Exception as e:
            return ToolResult(error=f"Session search error: {str(e)}")

    def _browse_recent(self, limit: int) -> ToolResult:
        """Browse recent sessions."""
        try:
            sessions_dir = os.path.join(self.root, "workspace", "sessions")
            if not os.path.exists(sessions_dir):
                return ToolResult(data="No recent sessions found.")
            
            files = sorted(Path(sessions_dir).glob("*.json"), key=os.path.getmtime, reverse=True)[:limit]
            if not files:
                return ToolResult(data="No session files found.")
            
            output = "### [RECENT SESSIONS]\n\n"
            for f in files:
                try:
                    data = json.load(open(f))
                    title = data.get("title", f.stem)
                    msg_count = len(data.get("messages", []))
                    ts = data.get("created_at", os.path.getmtime(f))
                    output += f"- {f.stem}: {title} ({msg_count} msgs)\n"
                except Exception: 
                    output += f"- {f.stem}\n"
            return ToolResult(data=output)
        except Exception as e:
            return ToolResult(error=str(e))

    def _search_json_sessions(self, query: str, limit: int) -> ToolResult:
        """Fallback: grep through JSON session files."""
        try:
            sessions_dir = os.path.join(self.root, "workspace", "sessions")
            if not os.path.exists(sessions_dir):
                return ToolResult(data=f"No matches for '{query}' in any session store.")
            
            import subprocess
            result = subprocess.run(
                ["grep", "-rl", query, sessions_dir],
                capture_output=True, text=True, timeout=5
            )
            files = result.stdout.strip().split("\n") if result.stdout.strip() else []
            
            if not files:
                return ToolResult(data=f"No matches for '{query}'.")
            
            output = f"### [JSON SESSION SEARCH] '{query}' found in:\n\n"
            for f in files[:limit]:
                output += f"- {os.path.basename(f)}\n"
            return ToolResult(data=output)
        except Exception as e:
            return ToolResult(error=str(e))

    def is_read_only(self, input_data=None):
        return True

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (keywords or phrase). Omit to browse recent sessions."},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                    "session_id": {"type": "string", "description": "Get full context for a specific session ID"},
                },
            },
        }
