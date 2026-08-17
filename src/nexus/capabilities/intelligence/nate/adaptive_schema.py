"""
NATE Layer 3: Adaptive Schema Engine — NATE-Route
Embedding-based semantic tool router (all-MiniLM-L6-v2 + FAISS).
Zero training. Any LLM. Any provider. 86% token savings.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import zlib
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TSCGCompressor — unchanged from original
# ─────────────────────────────────────────────────────────────────────────────

class TSCGCompressor:
    """Deterministic schema compressor.
    Renames fields: name->n, description->d, type->t, properties->p, required->r
    Drops: title, default, examples, additionalProperties when empty
    """

    SHORT_NAMES = {
        "name": "n",
        "description": "d",
        "type": "t",
        "properties": "p",
        "parameters": "p",
        "required": "r",
        "items": "i",
        "enum": "e",
        "minimum": "mn",
        "maximum": "mx",
        "minLength": "ml",
        "maxLength": "xl",
        "pattern": "pt",
        "format": "f",
        "default": "df",
    }

    DROP_KEYS = {"title", "examples", "additionalProperties", "$schema", "definitions"}

    @classmethod
    def compress(cls, schema: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        if depth > 10:
            return {"_ref": "..."}
        if not isinstance(schema, dict):
            return schema
        result = {}
        for k, v in schema.items():
            if k in cls.DROP_KEYS:
                continue
            short = cls.SHORT_NAMES.get(k, k)
            if isinstance(v, dict):
                result[short] = cls.compress(v, depth + 1)
            elif isinstance(v, list):
                result[short] = [cls.compress(item, depth + 1) if isinstance(item, dict) else item for item in v]
            else:
                result[short] = v
        return result

    @classmethod
    def compress_tool(cls, tool: Dict[str, Any]) -> Dict[str, Any]:
        return cls.compress(tool)

    @classmethod
    def savings_percent(cls, original: str, compressed: str) -> float:
        orig_len = len(original)
        comp_len = len(compressed)
        if orig_len == 0:
            return 0.0
        return round((1 - comp_len / orig_len) * 100, 1)


# ─────────────────────────────────────────────────────────────────────────────
# NATE-Route: Real embedding router (all-MiniLM-L6-v2 + FAISS)
# ─────────────────────────────────────────────────────────────────────────────

class NATE_Route:
    """Zero-training embedding router for tools.

    Uses all-MiniLM-L6-v2 for query embedding + FAISS for fast similarity search.
    Key features:
      - STRAP clustering: tools with cos-sim > 0.85 → grouped as one slot
      - Dynamic K: threshold-based cutoff (stop when sim drops)
      - Necessity gate: best sim < 0.30 → no tools (LLM answers directly)
      - Dual-path confidence: ≥0.50 or relative gap > 0.10 → Path 1, else Path 2
      - OATS feedback: interpolate embeddings toward success centroid
    """

    STRAP_THRESHOLD = 0.85
    NECESSITY_THRESHOLD = 0.22
    PATH1_THRESHOLD = 0.50
    RELATIVE_BONUS = 0.10
    DYNAMIC_K_MIN = 1
    DYNAMIC_K_MAX = 8
    SIM_DROP_THRESHOLD = 0.10
    FALLBACK_DIM = 512
    TRIGRAM_WEIGHT = 0.1
    MAX_FEEDBACK_HISTORY = 10

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._tool_names: List[str] = []
        self._tool_descriptions: List[str] = []
        self._tool_embeddings: Optional[np.ndarray] = None
        self._index = None
        self._clusters: Dict[int, List[int]] = {}
        self._cluster_centroids: Optional[np.ndarray] = None
        self._cluster_to_tool: Dict[int, int] = {}

        # TF-IDF corpus state (pure-NumPy fallback embedding)
        self._doc_freq: Dict[str, int] = {}
        self._num_docs = 0
        self._doc_terms: List[Dict[str, float]] = []
        self._vocab: Dict[str, int] = {}
        self._idf_weights: Dict[str, float] = {}
        self._vocab_dim = 0

        # OATS feedback accumulators
        self._feedback_success: Dict[str, List[np.ndarray]] = {}
        self._feedback_failure: Dict[str, List[np.ndarray]] = {}

        # Metrics
        self._metrics = {
            "total_queries": 0,
            "path1_count": 0,
            "path2_count": 0,
            "no_tool_count": 0,
            "avg_latency_ms": 0.0,
            "oats_updates": 0,
        }
        self._lock = threading.Lock()

    # ── Lazy model load ──────────────────────────────────────────────────

    def _lazy_load_model(self):
        if self._model is not None:
            return
        # NATE uses a pure-NumPy embedding fallback (hashing + char trigrams) by
        # default. The SentenceTransformer path is a heavy optional upgrade that
        # is OFF unless explicitly opted in via NATE_USE_TRANSFORMERS=true — it
        # pulls in torch/transformers and is known to crash (C stack overflow /
        # access violation) on some Python builds. Default behaviour is NumPy only.
        if os.environ.get("NATE_USE_TRANSFORMERS", "false").lower() != "true":
            self._model = None
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        except (ImportError, OSError, Exception) as e:
            self._model = None
            logger.warning(f"NATE model load failed: {e}")

    def _lazy_load_faiss(self):
        if self._index is not None or hasattr(self, "_faiss"):
            return
        try:
            import faiss
            self._faiss = faiss
        except ImportError:
            self._faiss = None
            if not getattr(self.__class__, '_faiss_warned', False):
                self.__class__._faiss_warned = True
                logger.warning("FAISS not installed, using numpy search fallback for NATE.")

    def _tokenize(self, text: str) -> List[str]:
        lowered = text.lower().replace("_", " ").replace("-", " ")
        return re.findall(r"[a-z0-9]+", lowered)

    def _term_weights(self, text: str) -> Dict[str, float]:
        """Raw term-frequency map: word tokens + character trigrams.

        Out-of-vocabulary query terms (e.g. a synonym like 'forecast' when no
        tool mentions it) are KEPT so their character trigrams can still overlap
        the tool vocabulary and contribute a weak signal, rather than being
        dropped entirely.
        """
        terms: Dict[str, float] = {}
        for token in self._tokenize(text):
            terms[f"tok:{token}"] = terms.get(f"tok:{token}", 0.0) + 1.0
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    tri = f"tri:{token[i : i + 3]}"
                    terms[tri] = terms.get(tri, 0.0) + self.TRIGRAM_WEIGHT
        return terms

    def _build_vocab(self) -> None:
        """Build the shared vocabulary + smoothed IDF weights from tool docs."""
        vocab: Dict[str, int] = {}
        df: Dict[str, int] = {}
        for terms in self._doc_terms:
            seen: set = set()
            for term in terms:
                if term not in vocab:
                    vocab[term] = len(vocab)
                if term not in seen:
                    seen.add(term)
                    df[term] = df.get(term, 0) + 1
        self._vocab = vocab
        n_docs = max(self._num_docs, 1)
        self._idf_weights = {
            term: math.log((1.0 + n_docs) / (1.0 + cnt)) + 1.0 for term, cnt in df.items()
        }
        self._vocab_dim = len(vocab)

    def _vectorize(self, terms: Dict[str, float]) -> np.ndarray:
        """Vocab-indexed TF-IDF vector (no hashing collisions).

        Only in-vocabulary terms contribute; out-of-vocabulary query terms
        (e.g. gibberish, or a synonym with no subword overlap) are dropped so
        they cannot spuriously collide with real tool vectors.
        """
        dim = max(getattr(self, "_vocab_dim", 0), 1)
        vec = np.zeros(dim, dtype=np.float32)
        if not terms:
            return vec
        for term, tf in terms.items():
            if tf <= 0:
                continue
            idx = self._vocab.get(term, -1)
            if idx < 0:
                continue
            idf = self._idf_weights.get(term, 1.0)
            vec[idx] += (1.0 + math.log(tf)) * idf
        norm = float(np.linalg.norm(vec))
        if norm > 0 and math.isfinite(norm):
            vec = vec / norm
        return vec

    def _fallback_encode(self, text: str) -> np.ndarray:
        """Pure-NumPy TF-IDF embedding (no external models)."""
        return self._vectorize(self._term_weights(text))

    def _recompute_tool_embeddings(self) -> None:
        """Re-encode every tool after the corpus IDF statistics changed.

        Only used on the pure-NumPy path; caller must hold ``self._lock``.
        """
        if not self._doc_terms:
            return
        self._build_vocab()
        self._tool_embeddings = np.vstack(
            [self._vectorize(terms) for terms in self._doc_terms]
        ).astype(np.float32)
        self._reindex_locked()

    def _reindex_locked(self) -> None:
        """Rebuild the FAISS index from the current embedding matrix."""
        if self._tool_embeddings is None:
            self._index = None
            return
        if getattr(self, "_faiss", None) is not None:
            self._index = self._faiss.IndexFlatIP(self._tool_embeddings.shape[1])
            self._index.add(self._tool_embeddings)
        else:
            self._index = None

    @staticmethod
    def _top_k(scores: np.ndarray, k: int):
        """Partition-based top-k (O(n)) followed by a sort of the k survivors."""
        n = int(scores.shape[0])
        k = max(0, min(int(k), n))
        if k == 0:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32)
        if k < n:
            cand = np.argpartition(-scores, k - 1)[:k]
        else:
            cand = np.arange(n)
        order = cand[np.argsort(-scores[cand], kind="stable")]
        return order, scores[order]

    def _encode_text(self, text: str) -> np.ndarray:
        self._lazy_load_model()
        if self._model is not None:
            emb = self._model.encode(text, normalize_embeddings=True)
            return np.asarray(emb, dtype=np.float32)
        return self._fallback_encode(text)

    # ── Tool registration ────────────────────────────────────────────────

    def register_tool(self, name: str, description: str = "") -> None:
        """Register a tool with its description for embedding."""
        self._lazy_load_faiss()
        with self._lock:
            self._tool_names.append(name)
            self._tool_descriptions.append(description)

            doc = f"{name} {description}"
            terms = self._term_weights(doc)
            self._doc_terms.append(terms)
            self._num_docs += 1
            for term in terms:
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

            self._lazy_load_model()
            if self._model is None:
                # TF-IDF weights depend on the whole corpus -> re-encode all tools.
                self._recompute_tool_embeddings()
            else:
                emb_2d = np.array([self._encode_text(doc)], dtype=np.float32)
                if self._tool_embeddings is None:
                    self._tool_embeddings = emb_2d
                else:
                    self._tool_embeddings = np.vstack([self._tool_embeddings, emb_2d])
                self._reindex_locked()

            self._rebuild_clusters()

    def _rebuild_clusters(self):
        """STRAP: cluster tools with cos-sim > STRAP_THRESHOLD."""
        self._clusters = {}
        self._cluster_centroids = None
        self._cluster_to_tool = {}

        if self._tool_embeddings is None or len(self._tool_names) == 0:
            return

        n = len(self._tool_names)
        assigned = [False] * n
        cluster_id = 0

        # One fused matmul gives the full pairwise cosine matrix.
        sim_matrix = self._tool_embeddings @ self._tool_embeddings.T

        for i in range(n):
            if assigned[i]:
                continue
            members = [i]
            assigned[i] = True
            for j in range(i + 1, n):
                if assigned[j]:
                    continue
                if float(sim_matrix[i, j]) >= self.STRAP_THRESHOLD:
                    members.append(j)
                    assigned[j] = True
            self._clusters[cluster_id] = members
            for idx in members:
                self._cluster_to_tool[idx] = cluster_id
            cluster_id += 1

        # Compute centroids
        centroids = []
        for cid, members in self._clusters.items():
            centroid = np.mean(self._tool_embeddings[members], axis=0)
            norm = float(np.linalg.norm(centroid))
            if norm > 0 and math.isfinite(norm):
                centroid = centroid / norm
            centroids.append(centroid)
        self._cluster_centroids = np.array(centroids, dtype=np.float32)

    def _cluster_display_name(self, cluster_id: int) -> str:
        """Return a display name for a cluster of similar tools."""
        members = self._clusters.get(cluster_id, [])
        if not members:
            return "unknown"
        names = [self._tool_names[i] for i in members]
        if len(names) == 1:
            return names[0]
        return f"[{'|'.join(names)}]"

    # ── Query routing ────────────────────────────────────────────────────

    def route(self, query: str) -> Dict[str, Any]:
        """Route a query to the best tools.

        Returns:
          path: "path1" | "path2" | "no_tools"
          tools: list of (tool_name, score) for selected tools
          confidence: max similarity score
          cluster_names: display names for selected clusters
          latency_ms: time taken for embedding + search
        """
        start = time.perf_counter()
        self._lazy_load_faiss()
        with self._lock:
            self._metrics["total_queries"] += 1

            if self._tool_embeddings is None or len(self._tool_names) == 0:
                return {
                    "path": "no_tools",
                    "tools": [],
                    "confidence": 0.0,
                    "cluster_names": [],
                    "latency_ms": (time.perf_counter() - start) * 1000,
                }

            q_emb = self._encode_text(query)

            # Single fused matmul over all tool embeddings + partition top-k.
            raw_scores = self._tool_embeddings @ q_emb
            k = min(len(self._tool_names), max(self.DYNAMIC_K_MAX, 2) + 1)
            idxs, scores = self._top_k(raw_scores, k)

            best_score = float(scores[0]) if len(scores) > 0 else 0.0
            second_score = float(scores[1]) if len(scores) > 1 else best_score
            relative_gap = best_score - second_score

            # Necessity gate
            if best_score < self.NECESSITY_THRESHOLD:
                self._metrics["no_tool_count"] += 1
                lat = (time.perf_counter() - start) * 1000
                return {
                    "path": "no_tools",
                    "tools": [],
                    "confidence": best_score,
                    "relative_gap": relative_gap,
                    "cluster_names": [],
                    "latency_ms": lat,
                }

            # Dynamic K: pick tools while similarity doesn't drop too much
            selected_idxs = []
            seen_clusters = set()
            for i in range(min(len(scores), self.DYNAMIC_K_MAX)):
                idx = int(idxs[i])
                score = float(scores[i])

                # Stop if similarity drops below threshold relative to best
                if best_score - score > self.SIM_DROP_THRESHOLD and len(selected_idxs) >= self.DYNAMIC_K_MIN:
                    break

                # STRAP: deduplicate by cluster
                if self._cluster_centroids is not None:
                    cid = self._cluster_to_tool.get(idx, idx)
                    if cid in seen_clusters:
                        continue
                    seen_clusters.add(cid)

                selected_idxs.append((idx, score))

                if len(selected_idxs) >= self.DYNAMIC_K_MAX:
                    break

            # Build result
            tools = []
            cluster_names = []
            for idx, score in selected_idxs:
                name = self._tool_names[int(idx)]
                if self._cluster_centroids is not None:
                    cid = self._cluster_to_tool.get(int(idx))
                    if cid is not None and len(self._clusters.get(cid, [])) > 1:
                        display = self._cluster_display_name(cid)
                        if display not in cluster_names:
                            cluster_names.append(display)
                            tools.append((name, float(score), display))
                            # Add all members of the cluster
                            for m in self._clusters[cid]:
                                m_name = self._tool_names[m]
                                m_score = float(raw_scores[m])
                                if m_name != name and (m_name, m_score, display) not in tools:
                                    tools.append((m_name, m_score, display))
                        continue
                tools.append((name, float(score), name))
                if name not in cluster_names:
                    cluster_names.append(name)

            # Remove duplicates (keep first occurrence)
            seen = set()
            deduped = []
            for t in tools:
                if t[0] not in seen:
                    seen.add(t[0])
                    deduped.append(t)
            tools = deduped

            # Path decision: absolute OR relative confidence
            uses_relative = relative_gap >= self.RELATIVE_BONUS and best_score >= self.NECESSITY_THRESHOLD
            path = "path1" if (best_score >= self.PATH1_THRESHOLD or uses_relative) else "path2"
            if path == "path1":
                self._metrics["path1_count"] += 1
            else:
                self._metrics["path2_count"] += 1

            lat = (time.perf_counter() - start) * 1000
            self._metrics["avg_latency_ms"] = (
                self._metrics["avg_latency_ms"] * (self._metrics["total_queries"] - 1) + lat
            ) / self._metrics["total_queries"]

            return {
                "path": path,
                "tools": tools,
                "confidence": best_score,
                "relative_gap": relative_gap,
                "cluster_names": cluster_names,
                "latency_ms": lat,
            }

    def get_tool_names_for_query(self, query: str) -> List[str]:
        """Return just the tool names (no scores) — convenience for schema loading."""
        result = self.route(query)
        return [t[0] for t in result["tools"]]

    # ── OATS feedback ────────────────────────────────────────────────────

    def record_feedback(self, tool_name: str, query: str, success: bool) -> None:
        """Record whether a tool was successful for a given query.

        OATS-style: embeddings interpolate toward success centroid over time.
        Hardened: ignores blank tool names/queries and degenerate embeddings.
        """
        if not isinstance(tool_name, str) or not tool_name.strip():
            logger.debug("NATE OATS: ignoring feedback with empty tool name")
            return
        if not isinstance(query, str) or not query.strip():
            logger.debug("NATE OATS: ignoring empty query for %s", tool_name)
            return

        q_emb = self._encode_text(query)
        if q_emb is None or not np.all(np.isfinite(q_emb)) or float(np.linalg.norm(q_emb)) <= 1e-8:
            logger.debug("NATE OATS: ignoring degenerate embedding for %s", tool_name)
            return

        with self._lock:
            bucket = self._feedback_success if success else self._feedback_failure
            history = bucket.setdefault(tool_name, [])
            history.append(np.asarray(q_emb, dtype=np.float32))

            # Keep only the most recent MAX_FEEDBACK_HISTORY samples
            if len(history) > self.MAX_FEEDBACK_HISTORY:
                del history[: len(history) - self.MAX_FEEDBACK_HISTORY]

    def apply_oats_feedback(self, decay: float = 0.1) -> int:
        """Interpolate tool embeddings toward success centroid.

        Called periodically (e.g., every 50 queries) to improve routing.
        Returns number of tools updated. Hardened: decay is clamped to [0, 1],
        non-finite/zero-norm updates are discarded, and the original embedding
        is preserved when an update would be degenerate.
        """
        try:
            decay = float(decay)
        except (TypeError, ValueError):
            decay = 0.1
        if not math.isfinite(decay):
            decay = 0.1
        decay = min(max(decay, 0.0), 1.0)

        with self._lock:
            if self._tool_embeddings is None or decay == 0.0:
                return 0

            updated = 0
            for i, name in enumerate(self._tool_names):
                if i >= self._tool_embeddings.shape[0]:
                    break
                successes = self._feedback_success.get(name, [])
                failures = self._feedback_failure.get(name, [])

                if not successes and not failures:
                    continue

                success_centroid = np.mean(successes, axis=0) if successes else None
                failure_centroid = np.mean(failures, axis=0) if failures else None

                shift = np.zeros_like(self._tool_embeddings[i])
                if success_centroid is not None:
                    shift += success_centroid * decay
                if failure_centroid is not None:
                    shift -= failure_centroid * (decay * 0.5)

                if not np.all(np.isfinite(shift)) or float(np.linalg.norm(shift)) <= 1e-8:
                    continue

                candidate = self._tool_embeddings[i] + shift
                norm = float(np.linalg.norm(candidate))
                if norm <= 1e-8 or not math.isfinite(norm):
                    # Degenerate update — keep the previous embedding.
                    continue
                self._tool_embeddings[i] = (candidate / norm).astype(np.float32)
                updated += 1

            # Rebuild index + clusters from the updated matrix
            if updated > 0:
                self._reindex_locked()
                self._rebuild_clusters()
                self._metrics["oats_updates"] += 1

            return updated

    # ── Stats ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "model": self._model_name,
            "num_tools": len(self._tool_names),
            "num_clusters": len(self._clusters),
            "total_queries": self._metrics["total_queries"],
            "path1_pct": round(self._metrics["path1_count"] / max(self._metrics["total_queries"], 1) * 100, 1),
            "path2_pct": round(self._metrics["path2_count"] / max(self._metrics["total_queries"], 1) * 100, 1),
            "no_tool_pct": round(self._metrics["no_tool_count"] / max(self._metrics["total_queries"], 1) * 100, 1),
            "avg_latency_ms": round(self._metrics["avg_latency_ms"], 2),
            "oats_updates": self._metrics["oats_updates"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# AdaptiveSchemaEngine — updated to use NATE_Route
# ─────────────────────────────────────────────────────────────────────────────

class AdaptiveSchemaEngine:
    """Fuses TSCG compression + NATE-Route embedding routing + lazy loading."""

    def __init__(self):
        self._raw_tools: Dict[str, Dict[str, Any]] = {}
        self._compressed_tools: Dict[str, Dict[str, Any]] = {}
        self.router = NATE_Route()
        self._always_loaded: List[str] = []

    def register_tool(self, tool: Dict[str, Any]) -> None:
        name = tool.get("name", tool.get("n", "unknown"))
        self._raw_tools[name] = tool
        compressed = TSCGCompressor.compress_tool(tool)
        self._compressed_tools[name] = compressed
        description = tool.get("description", tool.get("d", ""))
        self.router.register_tool(name, description)

    def register_many(self, tools: List[Dict[str, Any]]) -> None:
        for t in tools:
            self.register_tool(t)

    def set_always_loaded(self, names: List[str]) -> None:
        self._always_loaded = names

    def get_schemas(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        always = [
            self._compressed_tools.get(n, self._raw_tools.get(n))
            for n in self._always_loaded
            if n in self._raw_tools or n in self._compressed_tools
        ]

        route_result = self.router.route(query)
        lazy_names = [t[0] for t in route_result["tools"] if t[0] not in self._always_loaded]
        lazy = [
            self._compressed_tools.get(n, self._raw_tools.get(n))
            for n in lazy_names
            if n in self._compressed_tools or n in self._raw_tools
        ]

        return {
            "always_loaded": always,
            "lazy_loaded": lazy,
            "routed": route_result["tools"],
            "route_info": {
                "path": route_result["path"],
                "confidence": route_result["confidence"],
                "latency_ms": route_result["latency_ms"],
            },
        }

    def schema_stats(self) -> Dict[str, Any]:
        raw_total = sum(len(json.dumps(t)) for t in self._raw_tools.values())
        comp_total = sum(len(json.dumps(t)) for t in self._compressed_tools.values())
        return {
            "num_tools": len(self._raw_tools),
            "raw_bytes": raw_total,
            "compressed_bytes": comp_total,
            "savings_percent": TSCGCompressor.savings_percent(
                json.dumps(self._raw_tools), json.dumps(self._compressed_tools)
            ),
        }
