"""Failure vaccine engine: failure -> strategy -> memory -> regression plan."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional


@dataclass
class FailureVaccine:
    id: str
    task: str
    tool: str
    error: str
    failure_signature: str
    fix_strategy: str
    affected_files: List[str] = field(default_factory=list)
    severity: str = "medium"
    memory_node_id: str = ""
    strategy_id: str = ""
    test_files: List[str] = field(default_factory=list)
    test_commands: List[str] = field(default_factory=list)
    diagnostics_targets: List[str] = field(default_factory=list)
    status: str = "planned"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FailureVaccineEngine:
    """Converts concrete failures into durable prevention artifacts."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "failure_vaccines.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def create(
        self,
        task: str,
        error: str,
        fix_strategy: str,
        tool: str = "",
        affected_files: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> FailureVaccine:
        if not task.strip():
            raise ValueError("task is required")
        if not error.strip():
            raise ValueError("error is required")
        if not fix_strategy.strip():
            raise ValueError("fix_strategy is required")

        files = self._clean_files(affected_files or [])
        signature = self._signature(task, tool, error, files)

        from optimization.test_selection import TestSelector
        from sandbox.failure_memory import FailureMemory
        from cognition.memory_graph import AdaptiveMemoryGraph
        from cognition.self_improvement import SelfImprovementEngine

        FailureMemory(self.root).record(task, tool or "unknown", error, context or {"affected_files": files})
        strategy = SelfImprovementEngine(self.root).learn_from_failure(task, error, fix_strategy)
        memory = AdaptiveMemoryGraph(self.root).add(
            self._memory_text(task, error, fix_strategy, files),
            layer="failure",
            importance=0.9,
            confidence=0.85,
            tags=["failure_vaccine", "regression", *self._tag_terms(task + " " + error)],
            links=[strategy.id],
        )
        selection = TestSelector(self.root).select(files) if files else None
        vaccine = FailureVaccine(
            id=f"vaccine:{signature[:16]}",
            task=task.strip()[:500],
            tool=(tool or "unknown")[:120],
            error=error.strip()[:1000],
            failure_signature=signature,
            fix_strategy=fix_strategy.strip()[:1000],
            affected_files=files,
            severity=self._severity(error),
            memory_node_id=memory.id,
            strategy_id=strategy.id,
            test_files=selection.tests if selection else [],
            test_commands=selection.commands if selection else ["python -m compileall -q core tools orchestrators rag knowledge"],
            diagnostics_targets=selection.diagnostics_targets if selection else ["core", "tools/nexus_tools"],
        )
        self._append(vaccine)
        return vaccine

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        rows: List[Dict[str, Any]] = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        terms = set(self._tag_terms(query))
        scored: List[tuple[int, Dict[str, Any]]] = []
        for row in self.recent(limit=200):
            haystack = " ".join(
                [
                    str(row.get("task", "")),
                    str(row.get("tool", "")),
                    str(row.get("error", "")),
                    str(row.get("fix_strategy", "")),
                    " ".join(row.get("affected_files", [])),
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], item[1].get("created_at", 0)), reverse=True)
        return [row for _, row in scored[:limit]]

    def _append(self, vaccine: FailureVaccine) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(vaccine.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def _signature(task: str, tool: str, error: str, files: List[str]) -> str:
        raw = "\n".join([task.lower().strip(), tool.lower().strip(), error.lower().strip(), *files])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_files(files: List[str]) -> List[str]:
        cleaned = []
        for path in files:
            normalized = path.replace("\\", "/").strip().lstrip("/")
            if normalized and ".." not in normalized.split("/"):
                cleaned.append(normalized)
        return sorted(dict.fromkeys(cleaned))

    @staticmethod
    def _severity(error: str) -> str:
        lowered = error.lower()
        if any(token in lowered for token in ["secret", "token", "credential", "rce", "path traversal", "permission denied"]):
            return "critical"
        if any(token in lowered for token in ["crash", "traceback", "syntaxerror", "timeout", "data loss", "failed"]):
            return "high"
        if any(token in lowered for token in ["warning", "flake", "slow"]):
            return "low"
        return "medium"

    @staticmethod
    def _tag_terms(text: str) -> List[str]:
        terms = []
        for raw in text.lower().replace("_", " ").replace("-", " ").split():
            term = "".join(ch for ch in raw if ch.isalnum())
            if len(term) > 3 and term not in {"with", "from", "that", "this", "error", "failed"}:
                terms.append(term)
        return sorted(set(terms[:12]))

    @staticmethod
    def _memory_text(task: str, error: str, fix_strategy: str, files: List[str]) -> str:
        file_text = f" Affected files: {', '.join(files)}." if files else ""
        return (
            "Failure vaccine: when task resembles "
            f"'{task.strip()[:220]}' and error resembles '{error.strip()[:220]}', "
            f"apply strategy: {fix_strategy.strip()[:350]}.{file_text}"
        )
