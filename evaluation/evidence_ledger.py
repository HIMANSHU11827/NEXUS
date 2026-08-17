from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class EvidenceRecord:
    id: str
    claim: str
    evidence: List[Dict[str, Any]]
    status: str
    confidence: float
    mission_id: str
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "evidence": self.evidence,
            "status": self.status,
            "confidence": self.confidence,
            "mission_id": self.mission_id,
            "created_at": self.created_at,
        }


class EvidenceLedger:
    """Small durable evidence store used by the GUI audit/control plane."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "workspace", "evidence_ledger.jsonl")

    def record_claim(
        self,
        claim: str,
        *,
        evidence: List[Dict[str, Any]] | None = None,
        status: str = "supported",
        confidence: float = 0.8,
        mission_id: str = "default",
    ) -> EvidenceRecord:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        record = EvidenceRecord(
            id=f"evidence_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
            claim=str(claim or "").strip(),
            evidence=list(evidence or []),
            status=str(status or "unknown"),
            confidence=float(confidence),
            mission_id=str(mission_id or "default"),
            created_at=time.time(),
        )
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def _records(self, limit: int = 500) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        records: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records[-limit:]

    def audit_summary(self) -> Dict[str, Any]:
        records = self._records()
        by_status: Dict[str, int] = {}
        unsupported: List[Dict[str, Any]] = []
        for record in records:
            status = str(record.get("status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
            if status not in {"supported", "verified"}:
                unsupported.append(record)
        return {
            "total": len(records),
            "by_status": by_status,
            "unsupported_claims": unsupported[-8:],
            "latest": records[-5:],
        }
