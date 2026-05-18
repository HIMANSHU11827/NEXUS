"""Evidence ledger for truth-audited agent claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import time
from typing import Any, Dict, List


@dataclass
class EvidenceRecord:
    id: str
    claim: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "unverified"
    confidence: float = 0.0
    mission_id: str = "default"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceLedger:
    """Persistent claim/evidence store for auditable final answers and reports."""

    VALID_STATUSES = {"unverified", "supported", "contradicted", "stale"}

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "evidence_ledger.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record_claim(
        self,
        claim: str,
        evidence: List[Dict[str, Any]] | None = None,
        status: str = "unverified",
        confidence: float = 0.0,
        mission_id: str = "default",
    ) -> EvidenceRecord:
        claim = " ".join(str(claim or "").split())
        if not claim:
            raise ValueError("claim is required")
        if status not in self.VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")

        data = self._load()
        record_id = self._id_for(claim, mission_id)
        now = time.time()
        existing = data.get(record_id)
        if existing:
            merged_evidence = self._merge_evidence(existing.get("evidence", []), evidence or [])
            record = EvidenceRecord(
                id=record_id,
                claim=claim,
                evidence=merged_evidence,
                status=status,
                confidence=max(float(existing.get("confidence", 0.0)), self._bounded_confidence(confidence)),
                mission_id=mission_id,
                created_at=float(existing.get("created_at", now)),
                updated_at=now,
            )
        else:
            record = EvidenceRecord(
                id=record_id,
                claim=claim,
                evidence=self._merge_evidence([], evidence or []),
                status=status,
                confidence=self._bounded_confidence(confidence),
                mission_id=mission_id,
                created_at=now,
                updated_at=now,
            )
        data[record.id] = record.to_dict()
        self._save(data)
        return record

    def verify(self, record_id: str, status: str, confidence: float | None = None, evidence: List[Dict[str, Any]] | None = None) -> EvidenceRecord:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        data = self._load()
        if record_id not in data:
            raise ValueError(f"record not found: {record_id}")
        raw = data[record_id]
        raw["status"] = status
        if confidence is not None:
            raw["confidence"] = self._bounded_confidence(confidence)
        raw["evidence"] = self._merge_evidence(raw.get("evidence", []), evidence or [])
        raw["updated_at"] = time.time()
        data[record_id] = raw
        self._save(data)
        return EvidenceRecord(**raw)

    def recent(self, limit: int = 50, status: str = "", mission_id: str = "") -> List[Dict[str, Any]]:
        records = list(self._load().values())
        if status:
            records = [r for r in records if r.get("status") == status]
        if mission_id:
            records = [r for r in records if r.get("mission_id") == mission_id]
        records.sort(key=lambda r: float(r.get("updated_at", 0)), reverse=True)
        return records[:limit]

    def audit_summary(self) -> Dict[str, Any]:
        records = list(self._load().values())
        by_status: Dict[str, int] = {status: 0 for status in sorted(self.VALID_STATUSES)}
        for record in records:
            by_status[record.get("status", "unverified")] = by_status.get(record.get("status", "unverified"), 0) + 1
        unsupported = [r for r in records if r.get("status") in {"unverified", "contradicted"}]
        unsupported.sort(key=lambda r: (r.get("status") != "contradicted", -float(r.get("updated_at", 0))))
        return {
            "total": len(records),
            "by_status": by_status,
            "unsupported_claims": unsupported[:20],
        }

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: Dict[str, Dict[str, Any]]) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp, self.path)

    @staticmethod
    def _id_for(claim: str, mission_id: str) -> str:
        digest = hashlib.sha1(f"{mission_id}:{claim.lower()}".encode("utf-8")).hexdigest()[:12]
        return f"evidence:{digest}"

    @staticmethod
    def _bounded_confidence(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _merge_evidence(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for item in existing + new:
            if not isinstance(item, dict):
                item = {"note": str(item)}
            normalized = {
                "source": str(item.get("source", ""))[:500],
                "detail": str(item.get("detail", ""))[:2000],
                "kind": str(item.get("kind", "observation"))[:80],
            }
            key = (normalized["source"], normalized["detail"], normalized["kind"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
        return merged[:100]
