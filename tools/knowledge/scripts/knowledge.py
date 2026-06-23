from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class KnowledgeTool(BaseTool):
    name = "knowledge"
    description = "Query and manage the knowledge base"

    def _get_store(self) -> Path:
        d = Path(self.root_dir or ".") / "knowledge"
        d.mkdir(parents=True, exist_ok=True)
        return d / "store.json"

    def _load(self) -> List[Dict[str, Any]]:
        p = self._get_store()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return []

    async def execute(self, action: str, query: Optional[str] = None, title: Optional[str] = None, content: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            entries = self._load()
            if action == "list":
                lines = [f"{e['title']}: {e.get('content', '')[:60]}" for e in entries]
                return ToolResult(success=True, output="\n".join(lines) or "No knowledge entries")

            elif action == "store":
                if not title:
                    return ToolResult(success=False, error="title required")
                entries.append({"title": title, "content": content or "", "created": datetime.now().isoformat()})
                self._get_store().write_text(json.dumps(entries, indent=2), encoding="utf-8")
                return ToolResult(success=True, output=f"Stored knowledge: {title}")

            elif action == "query":
                if not query:
                    return ToolResult(success=True, output=str(entries)[:2000])
                results = [e for e in entries if query.lower() in e.get("content", "").lower() or query.lower() in e.get("title", "").lower()]
                return ToolResult(success=True, output=json.dumps(results, indent=2)[:2000])

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
