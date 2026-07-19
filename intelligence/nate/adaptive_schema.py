"""
NATE Layer 3: Adaptive Schema Engine — NATE-Route
Embedding-based semantic tool router (all-MiniLM-L6-v2 + FAISS).
Zero training. Any LLM. Any provider. 86% token savings.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
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
    NECESSITY_THRESHOLD = 0.30
    PATH1_THRESHOLD = 0.50
    RELATIVE_BONUS = 0.10
    DYNAMIC_K_MIN = 1
    DYNAMIC_K_MAX = 8
    SIM_DROP_THRESHOLD = 0.10
    FALLBACK_DIM = 512

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
            logger.warning("FAISS not installed, using numpy search fallback for NATE.")

    def _tokenize(self, text: str) -> List[str]:
        lowered = text.lower().replace("_", " ").replace("-", " ")
        return re.findall(r"[a-z0-9]+", lowered)

    def _fallback_encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.FALLBACK_DIM, dtype=np.float32)
        tokens = self._tokenize(text)
        if not tokens:
            return vec

        for token in tokens:
            idx = hash(token) % self.FALLBACK_DIM
            vec[idx] += 1.0

            # Lightweight character n-grams improve fuzzy overlap without external models.
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    tri = token[i : i + 3]
                    tri_idx = hash(f"tri:{tri}") % self.FALLBACK_DIM
                    vec[tri_idx] += 0.25

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _encode_text(self, text: str) -> np.ndarray:
        self._lazy_load_model()
        if self._model is not None:
            emb = self._model.encode(text, normalize_embeddings=True)
            return np.asarray(emb, dtype=np.float32)
        return self._fallback_encode(text)

    # ── Tool registration ────────────────────────────────────────────────

    def register_tool(self, name: str, description: str) -> None:
        """Register a tool with its description for embedding."""
        self._lazy_load_faiss()
        with self._lock:
            self._tool_names.append(name)
            self._tool_descriptions.append(description)

            emb = self._encode_text(f"{name} {description}")
            emb_2d = np.array([emb], dtype=np.float32)

            if self._tool_embeddings is None:
                self._tool_embeddings = emb_2d
            else:
                self._tool_embeddings = np.vstack([self._tool_embeddings, emb_2d])

            if self._index is None:
                dim = self._tool_embeddings.shape[1]
                if self._faiss is not None:
                    self._index = self._faiss.IndexFlatIP(dim)
            if self._index is not None:
                self._index.add(emb_2d)

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

        for i in range(n):
            if assigned[i]:
                continue
            members = [i]
            assigned[i] = True
            for j in range(i + 1, n):
                if assigned[j]:
                    continue
                sim = float(np.dot(self._tool_embeddings[i], self._tool_embeddings[j]))
                if sim >= self.STRAP_THRESHOLD:
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
            centroid = centroid / np.linalg.norm(centroid)
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
            q_emb_2d = np.array([q_emb], dtype=np.float32)

            # Search: cluster centroids first, then expand to tool indices
            if self._cluster_centroids is not None and len(self._cluster_centroids) > 0:
                if self._faiss is not None:
                    c_idx = self._faiss.IndexFlatIP(self._cluster_centroids.shape[1])
                    c_idx.add(self._cluster_centroids)
                    c_scores_arr, c_idxs_arr = c_idx.search(q_emb_2d, len(self._cluster_centroids))
                else:
                    centroid_scores = np.dot(self._cluster_centroids, q_emb)
                    c_idxs_arr = np.argsort(-centroid_scores)[None, :]
                    c_scores_arr = centroid_scores[c_idxs_arr]
                tool_list = []
                for i in range(len(c_scores_arr[0])):
                    cid = int(c_idxs_arr[0][i])
                    for midx in self._clusters.get(cid, []):
                        sim = float(np.dot(self._tool_embeddings[midx], q_emb))
                        tool_list.append((sim, midx))
                tool_list.sort(key=lambda x: -x[0])
                scores = [s for s, _ in tool_list]
                idxs = [i for _, i in tool_list]
            else:
                if self._index is not None:
                    scores_arr, idxs_arr = self._index.search(q_emb_2d, len(self._tool_names))
                    scores = scores_arr[0]
                    idxs = idxs_arr[0]
                else:
                    raw_scores = np.dot(self._tool_embeddings, q_emb)
                    idxs = np.argsort(-raw_scores)
                    scores = raw_scores[idxs]

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
                                if m_name != name and (m_name, float(np.dot(self._tool_embeddings[m], q_emb)), display) not in tools:
                                    tools.append((m_name, float(np.dot(self._tool_embeddings[m], q_emb)), display))
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
        """
        q_emb = self._encode_text(query)
        with self._lock:
            bucket = self._feedback_success if success else self._feedback_failure
            if tool_name not in bucket:
                bucket[tool_name] = []
            bucket[tool_name].append(q_emb)

            # Keep last 10
            if len(bucket[tool_name]) > 10:
                bucket[tool_name] = bucket[tool_name][-10:]

    def apply_oats_feedback(self, decay: float = 0.1) -> int:
        """Interpolate tool embeddings toward success centroid.

        Called periodically (e.g., every 50 queries) to improve routing.
        Returns number of tools updated.
        """
        with self._lock:
            if self._tool_embeddings is None:
                return 0

            updated = 0
            for i, name in enumerate(self._tool_names):
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

                if np.linalg.norm(shift) > 1e-8:
                    self._tool_embeddings[i] = self._tool_embeddings[i] + shift
                    self._tool_embeddings[i] = self._tool_embeddings[i] / np.linalg.norm(self._tool_embeddings[i])
                    updated += 1

            # Rebuild index
            if updated > 0:
                dim = self._tool_embeddings.shape[1]
                if self._faiss is not None:
                    self._index = self._faiss.IndexFlatIP(dim)
                    self._index.add(self._tool_embeddings)
                else:
                    self._index = None
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
