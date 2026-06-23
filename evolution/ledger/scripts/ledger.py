"""Evolution Ledger — tracks self-improvement metrics over time."""
__version__ = "1.0.0"
import json
import logging
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class EvolutionLedger:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "logs", "evolution_ledger.jsonl")
        self.summary_path = os.path.join(self.root, "logs", "evolution_summary.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, kind: str, summary: str, detail: str = "", metadata: Dict = None) -> Dict[str, Any]:
        entry = {"id": f"ev:{int(time.time())}:{hash(summary) & 0xFFFF:04x}", "kind": kind, "summary": summary, "detail": detail, "metadata": metadata or {}, "timestamp": time.time()}
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Ledger write failed: {e}")
        return entry

    def summary(self) -> Dict[str, Any]:
        entries = self._read_all()
        by_kind = Counter(e.get("kind", "unknown") for e in entries)
        return {"total_events": len(entries), "by_kind": dict(by_kind), "applied": sum(1 for e in entries if e.get("metadata", {}).get("applied")), "active_days": len(set(e.get("timestamp", 0) // 86400 for e in entries))}

    def _read_all(self) -> List[Dict[str, Any]]:
        entries = []
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))
            except Exception:
                pass
        return entries
