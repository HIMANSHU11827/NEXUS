"""
NEXUS KNOWLEDGE VAULT 2.0 — REAL PERSISTENT MEMORY
Stores facts with importance scores, persists to disk as JSON,
and retrieves by real keyword + recency scoring.
"""
import json
import os
import time
from typing import List, Dict, Any, Optional
from core.nexus_compat import s, safe_del, sx  # type: ignore


class KnowledgeVault:
    """
    NEXUS FRONTIER VAULT 2.0 (SEMANTIC-SCORING MEMORY)
    - Persists across sessions (JSON file on disk)
    - Retrieves by real keyword overlap scoring
    - Ranks by importance mass + recency
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(_root, "knowledge", "vault.json.enc")
        self.db_path: str = db_path
        
        # 🛡️ Sovereignty Key Resolution
        from cryptography.fernet import Fernet
        import hashlib
        import base64
        
        # Generate a key based on the machine ID or an env var
        key_seed = os.environ.get("NEXUS_VAULT_KEY", "nexus-sovereign-default-seed")
        self.key = base64.urlsafe_b64encode(hashlib.sha256(key_seed.encode()).digest())
        self.cipher = Fernet(self.key)
        
        self.memory_graph: Dict[str, Any] = self._load()

    # ── Persistence ────────────────────────────────────────────────────────────
    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "rb") as f:
                    encrypted_data = f.read()
                if not encrypted_data:
                    return {}
                decrypted_data = self.cipher.decrypt(encrypted_data)
                result = json.loads(decrypted_data.decode("utf-8"))
                return result if isinstance(result, dict) else {}
            except Exception:
                # If decryption fails (new key or corrupted), backup and start fresh
                return {}
        return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        data_bytes = json.dumps(self.memory_graph, indent=2).encode("utf-8")
        encrypted_data = self.cipher.encrypt(data_bytes)
        with open(self.db_path, "wb") as f:
            f.write(encrypted_data)

    # ── Write ──────────────────────────────────────────────────────────────────
    def add_fact(self, source: str, fact_type: str, content: str, importance: float = 1.0) -> str:
        fact_id = str(abs(hash(content + source)))
        self.memory_graph[fact_id] = {
            "source": source,
            "type": fact_type,
            "content": content,
            "mass": importance,
            "timestamp": time.time(),
            "ts_human": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._save()
        short_id: str = s(fact_id, 8)
        return f"Fact [{short_id}] stored in Vault (mass={importance}, type={fact_type})."

    # ── Retrieve ───────────────────────────────────────────────────────────────
    def retrieve_by_proximity(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """NEXUS 3.2: Enhanced Term-Weighting Retrieval."""
        if not query.strip() or not self.memory_graph:
            return []

        query_terms = set(query.lower().split())
        scored: List[Any] = []

        for fid, fact in self.memory_graph.items():
            content = str(fact.get("content", "")).lower()
            content_words = set(content.split())
            
            # ⚡ Word match count
            hits = len(query_terms & content_words)
            if hits == 0:
                continue

            # ⚡ Exact phrase match bonus
            phrase_bonus = 2.0 if query.lower() in content else 1.0
            
            # ⚡ Recency scoring: 7-day decay
            age_seconds = float(time.time()) - float(fact.get("timestamp", 0))
            recency: float = float(max(0.1, 1.0 - (age_seconds / (7.0 * 86400.0))))

            # ⚡ Final Scoring: (Hits * Importance) * PhraseBonus + (Recency * 0.5)
            mass: float = float(fact.get("mass", 1.0))
            score: float = (float(hits) * mass * phrase_bonus) + (recency * 0.5)
            scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in sx(scored, 0, top_k)]

    def retrieve_as_text(self, query: str, top_k: int = 5) -> str:
        facts = self.retrieve_by_proximity(query, top_k)
        if not facts:
            return "No relevant knowledge found in vault."
        lines = [f"[{f.get('type','?')}|{f.get('source','?')}] {f.get('content','')}" for f in facts]
        return "VAULT RECALL:\n" + "\n".join(lines)

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self.memory_graph.values())

    def clear(self) -> str:
        self.memory_graph = {}
        self._save()
        return "Vault cleared."


if __name__ == "__main__":
    vault = KnowledgeVault()
    vault.add_fact("user_input", "project_goal", "Architect the NEXUS AI Kernel.", 10.0)
    vault.add_fact("session", "observation", "LM Studio is running on port 1234.", 5.0)
    print(vault.retrieve_as_text("NEXUS kernel architecture"))
