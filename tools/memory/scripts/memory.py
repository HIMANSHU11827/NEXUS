from __future__ import annotations
__version__ = "1.0.0"
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class MemoryTool(BaseTool):
    name = "memory"
    description = "Store and retrieve memories"

    def _get_store(self) -> Path:
        d = Path(self.root_dir or ".") / ".nexus" / "memory"
        d.mkdir(parents=True, exist_ok=True)
        return d / "store.json"

    def _load(self) -> Dict[str, Any]:
        p = self._get_store()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _save(self, data: Dict[str, Any]):
        self._get_store().write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def execute(self, action: str, key: Optional[str] = None, content: Optional[str] = None, query: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            store = self._load()
            if action == "store":
                if not key or content is None:
                    return ToolResult(success=False, error="key and content required")
                store[key] = {"content": content, "timestamp": datetime.now().isoformat()}
                self._save(store)
                return ToolResult(success=True, output=f"Stored memory: {key}")

            elif action == "retrieve":
                if not key:
                    return ToolResult(success=False, error="key required")
                entry = store.get(key)
                if entry:
                    return ToolResult(success=True, output=entry["content"])
                return ToolResult(success=False, error=f"Memory not found: {key}")

            elif action == "search":
                if not query:
                    return ToolResult(success=True, output="\n".join(store.keys()))
                matches = [k for k in store.values() if query.lower() in k["content"].lower()]
                return ToolResult(success=True, output=str(matches))

            elif action == "list":
                return ToolResult(success=True, output="\n".join(store.keys()) or "No memories stored")

            elif action == "delete":
                if key and key in store:
                    del store[key]
                    self._save(store)
                    return ToolResult(success=True, output=f"Deleted memory: {key}")
                return ToolResult(success=False, error=f"Memory not found: {key}")

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
