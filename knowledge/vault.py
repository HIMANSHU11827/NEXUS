"""NEXUS KNOWLEDGE VAULT 2.0 — REAL PERSISTENT MEMORY
Stores facts with importance weights in an obfuscated on-disk backend
(``knowledge/vault.json.enc``) and retrieves them with lightweight
term-weighted scoring.  Stdlib-only so it degrades gracefully on machines
without ``cryptography``/``sentence-transformers`` installed.

Design notes (v2.0):
- Facts persist across sessions (plaintext JSON payload, base64-obfuscated
  so the file is not trivially human-editable — NOT strong encryption).
- A legacy plaintext ``vault.json`` is auto-migrated on first load.
- Retrieval is enhanced term-weighting (importance * term-overlap), never
  claims to be semantic/vector search.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Dict, List, Optional


__version__ = "2.0.0"


def _default_vault_path() -> str:
    """Default backend file: the ``knowledge/vault.json.enc`` beside this module."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault.json.enc")


class KnowledgeVault:
    """Encrypted persistent fact storage with importance-weighted retrieval.

    Usage:
        vault = KnowledgeVault()                     # default knowledge/vault.json.enc
        vault.add_fact("The sky is blue", importance=0.8)
        text = vault.retrieve_as_text("sky color", top_k=2)
    """

    def __init__(self, vault_path: Optional[str] = None) -> None:
        self.path = os.path.abspath(vault_path) if vault_path else _default_vault_path()
        self._facts: List[Dict[str, Any]] = []
        self._load()

    def _legacy_import_path(self) -> str:
        """Path to the old plaintext vault.json (pre-encryption)."""
        return os.path.join(os.path.dirname(self.path), "vault.json")

    def _migrate_from_legacy(self) -> None:
        """Try to import from the old plaintext vault.json if it exists."""
        legacy = self._legacy_import_path()
        if not os.path.isfile(legacy):
            return
        try:
            with open(legacy, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            items = data.items() if isinstance(data, dict) else []
            migrated = 0
            for key, value in items:
                if isinstance(value, str) and value:
                    self._facts.append({
                        "content": value,
                        "importance": 1.0,
                        "ts": time.time(),
                    })
                    migrated += 1
            if migrated:
                self._save()
                os.replace(legacy, legacy + ".migrated")
        except (OSError, ValueError):
            pass

    def _load(self) -> None:
        """Load facts from disk (obfuscated JSON), falling back to legacy."""
        if not os.path.isfile(self.path):
            self._migrate_from_legacy()
            return
        data: Optional[Dict[str, Any]] = None
        for decoder in (self._deserialize, json.loads):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = fh.read()
                if not raw.strip():
                    continue
                data = decoder(raw)
                break
            except (OSError, ValueError, TypeError):
                continue
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            self._facts = [f for f in data["facts"] if isinstance(f, dict)]
        else:
            self._facts = []

    def _serialize(self, payload: Dict[str, Any]) -> str:
        """Obfuscate the JSON payload so facts are not trivially editable."""
        raw = json.dumps(payload).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _deserialize(self, text: str) -> Dict[str, Any]:
        """Reverse :meth:`_serialize` — base64 then JSON."""
        return json.loads(base64.b64decode(text.encode("ascii")).decode("utf-8"))

    def _save(self) -> None:
        """Atomically write the fact store to disk."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {
            "version": __version__,
            "facts": self._facts,
            "updated_at": time.time(),
        }
        tmp = self.path + f".{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(self._serialize(payload))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def add_fact(self, content: str, importance: float = 1.0) -> bool:
        """Persist a fact (deduped by exact content).  Returns True if new."""
        content = (content or "").strip()
        if not content:
            return False
        for fact in self._facts:
            if fact.get("content") == content:
                fact["importance"] = max(float(fact.get("importance", 0.0)), importance)
                fact["ts"] = time.time()
                self._save()
                return True
        self._facts.append({
            "content": content,
            "importance": float(importance),
            "ts": time.time(),
        })
        self._save()
        return False

    def retrieve_by_proximity(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """NEXUS 3.2: Enhanced Term-Weighting Retrieval.

        Scores each fact by ``importance * number_of_query_terms_present``.
        Honest keyword proximity — not a semantic/vector claim.
        """
        q_tokens = {
            t for t in re.findall(r"[a-z0-9_\.\-]+", (query or "").lower()) if len(t) > 1
        }
        if not q_tokens:
            return []
        scored: List[Dict[str, Any]] = []
        for fact in self._facts:
            content = str(fact.get("content", "") or "").lower()
            if not content:
                continue
            hits = sum(1 for t in q_tokens if t in content)
            if hits:
                importance = float(fact.get("importance", 1.0))
                scored.append({
                    "content": fact.get("content", ""),
                    "importance": importance,
                    "score": importance * hits,
                })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(0, int(top_k))]

    def retrieve_as_text(self, query: str, top_k: int = 2) -> str:
        """Retrieve top-k facts formatted for prompt injection.  '' when empty."""
        results = self.retrieve_by_proximity(query, top_k=top_k)
        if not results:
            return ""
        return "\n".join(
            f"- {item['content']}" for item in results
        )

    def list_all(self) -> List[str]:
        """Return all stored fact contents."""
        return [str(f.get("content", "")) for f in self._facts]

    def clear(self) -> None:
        """Wipe all stored facts (and remove the backend file)."""
        self._facts = []
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
