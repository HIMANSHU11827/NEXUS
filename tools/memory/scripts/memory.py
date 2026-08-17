from __future__ import annotations

__version__ = "2.0.0"
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from memory import MemoryBudget, estimate_tokens


class MemoryTool(BaseTool):
    name = "memory"
    description = "Store and retrieve memories"

    def __init__(self, root_dir: Optional[str] = None, budget: Optional[MemoryBudget] = None):
        super().__init__(root_dir)
        self.budget = budget or MemoryBudget()

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
        self.assert_execution_active()
        self._get_store().write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def execute(self, action: str, key: Optional[str] = None, content: Optional[str] = None, query: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            store = self._load()
            if action == "store":
                if not key or content is None:
                    return ToolResult(success=False, error="key and content required")
                # Token budget: truncate oversized values with an explicit
                # ``[truncated N chars]`` marker — never a silent discard —
                # then cap total store growth (oldest unverified evicted first).
                content_text = content if isinstance(content, str) else str(content)
                fitted = self.budget.fit_value(content_text)
                truncated = fitted != content_text
                # Provenance gate: unverified LLM claims are the default and are
                # recorded as such.  An entry is only marked verified when the
                # caller cites a verified run result (``verified_result_id`` /
                # ``evidence``) rather than a bare llm claim.
                verified = bool(kwargs.get("verified_result_id") or kwargs.get("evidence"))
                source = str(kwargs.get("source") or ("verified_result" if verified else "llm_claim"))
                store[key] = {
                    "content": fitted,
                    "source": source,
                    "verified": verified,
                    "verified_result_id":
                        str(kwargs.get("verified_result_id") or "") or None,
                    "timestamp": datetime.now().isoformat(),
                }
                evicted = self.budget.trim_store(store)
                self._save(store)
                out = f"Stored memory: {key}"
                if truncated:
                    out += f" (content truncated to {len(fitted)} chars)"
                if evicted:
                    out += f" (trimmed {evicted} low-value memories)"
                return ToolResult(
                    success=True,
                    output=out,
                    metadata={
                        "truncated": truncated,
                        "evicted": evicted,
                        "est_tokens": estimate_tokens(fitted),
                    },
                )

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
                matches = [k for k, v in store.items() if query.lower() in v["content"].lower()]
                return ToolResult(success=True, output="\n".join(matches) or "No memories matched")

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
