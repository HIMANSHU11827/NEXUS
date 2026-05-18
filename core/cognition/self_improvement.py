"""Failure-to-strategy learning and benchmark tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import time
from typing import Any, Dict, List


@dataclass
class StrategyRecord:
    id: str
    trigger: str
    strategy: str
    wins: int = 0
    failures: int = 0
    evidence: List[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class SelfImprovementEngine:
    """Stores winning strategies and turns failures into reusable rules."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "self_improvement.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.strategies: Dict[str, StrategyRecord] = {}
        self._load()

    def learn_from_failure(self, task: str, error: str, fix: str) -> StrategyRecord:
        trigger = self._trigger(task, error)
        strategy_id = f"strategy:{abs(hash(trigger))}"
        record = self.strategies.get(strategy_id) or StrategyRecord(strategy_id, trigger, fix)
        record.failures += 1
        record.strategy = fix
        record.evidence.append(f"failure: {error[:300]}")
        record.updated_at = time.time()
        self.strategies[record.id] = record
        self._save()
        return record

    def record_win(self, task: str, strategy: str, evidence: str = "") -> StrategyRecord:
        trigger = self._trigger(task, strategy)
        strategy_id = f"strategy:{abs(hash(trigger))}"
        record = self.strategies.get(strategy_id) or StrategyRecord(strategy_id, trigger, strategy)
        record.wins += 1
        if evidence:
            record.evidence.append(f"win: {evidence[:300]}")
        record.updated_at = time.time()
        self.strategies[record.id] = record
        self._save()
        return record

    def recommend(self, task: str, limit: int = 5) -> List[StrategyRecord]:
        terms = set(task.lower().split())
        scored = []
        for record in self.strategies.values():
            score = sum(1 for term in terms if term in record.trigger.lower() or term in record.strategy.lower())
            score += record.wins * 2 - record.failures * 0.5
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.strategies = {k: StrategyRecord(**v) for k, v in raw.items()}
        except Exception:
            self.strategies = {}

    def _save(self) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.strategies.items()}, f, indent=2)
        os.replace(temp, self.path)

    @staticmethod
    def _trigger(task: str, signal: str) -> str:
        return " ".join((task + " " + signal).lower().split()[:40])
