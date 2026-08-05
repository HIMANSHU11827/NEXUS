from __future__ import annotations

__version__ = "2.0.0"
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from memory import MemoryBudget


class KnowledgeTool(BaseTool):
    name = "knowledge"
    description = "Query and manage the knowledge base"

    def __init__(self, root_dir: Optional[str] = None, budget: Optional[MemoryBudget] = None):
        super().__init__(root_dir)
        self.budget = budget or MemoryBudget()

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
                # Token budget: truncate oversized values with an explicit
                # ``[truncated N chars]`` marker — never a silent discard —
                # then cap total store growth (oldest unverified evicted first).
                content_text = content if isinstance(content, str) else str(content or "")
                fitted = self.budget.fit_value(content_text)
                truncated = fitted != content_text
                entries.append({"title": title, "content": fitted, "created": datetime.now().isoformat()})
                evicted = self.budget.trim_store(entries)
                self._get_store().write_text(json.dumps(entries, indent=2), encoding="utf-8")
                out = f"Stored knowledge: {title}"
                if truncated:
                    out += f" (content truncated to {len(fitted)} chars)"
                if evicted:
                    out += f" (trimmed {evicted} low-value entries)"
                return ToolResult(
                    success=True,
                    output=out,
                    metadata={"truncated": truncated, "evicted": evicted},
                )

            elif action == "query":
                if not query:
                    return ToolResult(success=True, output=str(entries)[:2000])
                q = str(query).lower()
                q_tokens = q.split()
                scored: List[tuple] = []
                for e in entries:
                    title = str(e.get("title", "")).lower()
                    content = str(e.get("content", "")).lower()
                    haystack = title + "\n" + content
                    # Exact substring match ranks first (strongest signal).
                    if q in haystack:
                        scored.append((5.0, e))
                    else:
                        hits = sum(1 for t in q_tokens if t in haystack)
                        if hits:
                            scored.append((1.0 * hits, e))
                scored.sort(key=lambda item: item[0], reverse=True)
                results = [e for _score, e in scored]
                return ToolResult(success=True, output=json.dumps(results, indent=2)[:2000])

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
