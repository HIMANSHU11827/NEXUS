"""Zero-token context pointers and compressed intelligence packets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import time
from typing import Any, Dict, List


@dataclass
class ContextPacket:
    id: str
    title: str
    summary: str
    pointers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class ZeroTokenContextEngine:
    """Stores compact summaries and pointer IDs instead of replaying raw context."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.path = os.path.join(self.root, "workspace", "context_packets.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.packets: Dict[str, ContextPacket] = {}
        self._load()

    def create_packet(self, title: str, content: str, pointers: List[str] | None = None, metadata: Dict[str, Any] | None = None) -> ContextPacket:
        summary = self._summarize(content)
        digest = hashlib.sha1((title + summary + json.dumps(pointers or [])).encode("utf-8")).hexdigest()[:12]
        packet = ContextPacket(f"ctx:{digest}", title, summary, pointers or [], metadata or {})
        self.packets[packet.id] = packet
        self._save()
        return packet

    def route(self, query: str, limit: int = 5) -> List[ContextPacket]:
        terms = set(query.lower().split())
        scored = []
        for packet in self.packets.values():
            haystack = f"{packet.title} {packet.summary}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, packet))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [packet for _, packet in scored[:limit]]

    def purge_duplicates(self) -> int:
        seen = {}
        removed = 0
        for packet_id, packet in list(self.packets.items()):
            key = packet.summary.lower()
            if key in seen:
                del self.packets[packet_id]
                removed += 1
            else:
                seen[key] = packet_id
        if removed:
            self._save()
        return removed

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.packets = {k: ContextPacket(**v) for k, v in raw.items()}
        except Exception:
            self.packets = {}

    def _save(self) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.packets.items()}, f, indent=2)
        os.replace(temp, self.path)

    @staticmethod
    def _summarize(content: str, max_chars: int = 900) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        joined = " ".join(lines)
        return joined[:max_chars]
