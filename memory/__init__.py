"""Unified MemoryManager — central orchestrator for all NEXUS memory systems.

Provides a single ``prefetch_all(user_msg)`` / ``sync_all(user_msg, response)``
API that wraps session memory, failure memory, RAG, knowledge vault, evolution
memory forge, and .opencode/memory/ files (Hermes-inspired architecture).

``sync_all`` accepts verified turn evidence (``verified_actions`` /
``tool_results``); durable fact sinks are gated on it so raw model prose is
never stored as a cross-session learning.

Token economics live here too: ``estimate_tokens`` (chars//4),
``MemoryBudget`` (per-write + store-growth caps with explicit elision
markers), and ``expire`` (age/hard-cap eviction, verified-facts-exempt).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from nexus.runtime import safe_session_id
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .continuity import inspect_continuity, _timestamp
from providers.reliability import redact_secrets

logger = logging.getLogger("nexus.memory")

_REPLAY_FILE_REL = os.path.join(".nexus_v5", "replays.jsonl")
_MEMORY_EVIDENCE_REL = os.path.join(".nexus_v5", "memory_evidence.jsonl")
_MEMORY_EVIDENCE_LOCK = threading.Lock()
_EPISODIC_RECENCY_WINDOW = 86400.0
_EPISODIC_RECENCY_ALPHA = 0.4
_EPISODIC_RELEVANCE_BETA = 0.3
_EPISODIC_IMPORTANCE_GAMMA = 0.3


def _sanitize_recalled_text(value: Any) -> str:
    """Redact credentials at the memory-to-model egress boundary."""
    try:
        return redact_secrets(str(value or ""))
    except Exception:
        return str(value or "")


def _episodic_entry_failed(entry: Any) -> bool:
    """True when a replay entry carries failure/error signals."""
    if not isinstance(entry, dict):
        return False
    n_failed = entry.get("n_failed", 0)
    if isinstance(n_failed, (int, float)) and n_failed > 0:
        return True
    if bool(entry.get("error")) or bool(entry.get("failure")):
        return True
    return entry.get("success") is False


def _episodic_score_entry(entry: Any, now: float) -> float:
    """Smallville-style recency·α + relevance·β + importance·γ, in 0..1."""
    if not isinstance(entry, dict):
        return 0.0
    try:
        recency = 0.0
        timestamp = entry.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            try:
                parsed = datetime.datetime.fromisoformat(timestamp)
                age = max(0.0, now - parsed.timestamp())
                recency = math.exp(-age / _EPISODIC_RECENCY_WINDOW)
            except Exception:
                recency = 0.0
        failed = _episodic_entry_failed(entry)
        if failed:
            relevance = 1.0
        elif entry.get("type") == "reflection" or "root_causes" in entry or "reflection" in entry:
            relevance = 0.8
        elif isinstance(entry.get("plan_steps", 0), (int, float)) and entry.get("plan_steps", 0) > 0:
            relevance = 0.6
        else:
            relevance = 0.3
        importance = 1.0 if failed else 0.5
        score = (
            recency * _EPISODIC_RECENCY_ALPHA
            + relevance * _EPISODIC_RELEVANCE_BETA
            + importance * _EPISODIC_IMPORTANCE_GAMMA
        )
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.0


def _episodic_query_relevance(entry: Any, query: str) -> float:
    """Return lexical query coverage for an episodic entry (0..1)."""
    if not isinstance(entry, dict) or not str(query or "").strip():
        return 0.0
    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9_]+", str(query).lower())
        if len(token) > 1
    }
    if not query_tokens:
        return 0.0
    searchable = " ".join(
        str(entry.get(field) or "")
        for field in (
            "input",
            "output",
            "error",
            "failure",
            "reflection",
            "root_causes",
        )
    ).lower()
    entry_tokens = {
        token
        for token in re.findall(r"[a-z0-9_]+", searchable)
        if len(token) > 1
    }
    return len(query_tokens & entry_tokens) / len(query_tokens)


def _tool_evidence_text(
    results: List[Dict[str, Any]], limit: int = 500
) -> str:
    """Compact plain-text digest of verified tool outputs.

    Extracts the output/error from each tool result for durable memory,
    up to *limit* characters total.  Never raises; returns "" on error.
    """
    if not results:
        return ""
    try:
        pieces: List[str] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            ok = r.get("verified", r.get("success", False))
            tool = str(r.get("tool") or r.get("name") or "").strip()
            out = str(r.get("output") or "").strip()
            err = str(r.get("error") or "").strip()
            desc = str(r.get("description") or "").strip()
            label = desc or tool or "tool"
            if not ok and err:
                pieces.append(f"{label} FAILED: {err[:200]}")
            elif ok and out:
                pieces.append(f"{label}: {out[:200]}")
            elif ok:
                pieces.append(f"{label}: completed")
        text = "; ".join(pieces)
        if len(text) > limit:
            text = text[:limit].rstrip() + "…"
        return text
    except Exception:
        return ""


def estimate_tokens(text: Any) -> int:
    """Rough token estimate for budgeting — ~4 characters per token.

    ``chars // 4`` is a deliberate, cheap approximation of token counts for
    English text.  Used to cap memory writes and to budget context compaction.
    """
    if text is None:
        return 0
    return len(str(text)) // 4


_ELISION_MARKER = "[truncated {} chars]"


def _truncate_with_marker(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, appending an explicit elision marker.

    Nothing is ever silently discarded — the marker states exactly how many
    characters were elided.
    """
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars)] + _ELISION_MARKER.format(len(text) - max_chars)


def _entry_meta(entry: Any) -> tuple:
    """``(ts_epoch, verified)`` for a stored entry — soft-degrades on gaps.

    Missing/malformed timestamps count as "recent" (never age-evicted); a
    missing ``verified`` key is treated as unverified (low-value, evictable).
    """
    if not isinstance(entry, dict):
        return 0.0, False
    ts = 0.0
    raw = entry.get("timestamp") or entry.get("created")
    if isinstance(raw, str) and raw:
        try:
            ts = datetime.datetime.fromisoformat(raw).timestamp()
        except Exception:
            ts = 0.0
    return ts, bool(entry.get("verified", False))


@dataclass
class MemoryBudget:
    """Per-write and store-growth token budget for durable memory.

    Attributes:
        max_fact_tokens: cap for a single stored fact (~4 chars/token).
        max_entries: cap on total store size.

    Oversized values are truncated with an explicit ``[truncated N chars]``
    marker (``fit_value``) — never a silent discard.  Store growth is trimmed
    oldest/low-value-first (``trim_store``); recent verified facts are never
    silently dropped.
    """

    max_fact_tokens: int = 2000
    max_entries: int = 10000

    def estimate_tokens(self, text: Any) -> int:
        """Token estimate for *text* (``chars // 4``)."""
        return estimate_tokens(text)

    def max_fact_chars(self) -> int:
        """Char budget equivalent of ``max_fact_tokens``."""
        return max(1, self.max_fact_tokens * 4)

    def fit_value(self, text: str, max_chars: Optional[int] = None) -> str:
        """Fit *text* to the per-write budget, appending an elision marker."""
        if not text:
            return ""
        cap = self.max_fact_chars() if max_chars is None else max_chars
        return _truncate_with_marker(text, cap)

    def trim_store(self, store: Any, max_entries: Optional[int] = None) -> int:
        """Evict oldest low-value entries until the store fits the cap.

        Drop priority is unverified-and-oldest first, verified-and-newest
        last, so recent verified facts survive.  Mutates the container in
        place (dict ``{key: entry}`` or list of entries) and returns the
        number of entries evicted.
        """
        cap = self.max_entries if max_entries is None else max_entries
        is_list = isinstance(store, list)
        pairs = (
            [(str(i), entry) for i, entry in enumerate(store)]
            if is_list else list(store.items())
        )
        if len(pairs) <= cap:
            return 0
        scored: List[tuple] = []
        for key, entry in pairs:
            ts, verified = _entry_meta(entry)
            scored.append((ts, verified, key, entry))
        # Ascending sort = drop priority: unverified first, oldest first.
        scored.sort(key=lambda item: (item[1], item[0], item[2]))
        evicted = len(scored) - cap
        kept = scored[evicted:]
        if is_list:
            del store[:]
            store.extend(entry for _ts, _ver, _k, entry in kept)
        else:
            store.clear()
            store.update({key: entry for _ts, _ver, key, entry in kept})
        return evicted


def expire(
    store: Any,
    max_age_days: int = 90,
    max_entries: int = 10000,
    now: Optional[float] = None,
) -> tuple:
    """Evict expired, low-value memory entries; verified facts survive.

    - Unverified entries older than ``max_age_days`` are evicted first
      (oldest first).
    - Verified facts are exempt from age-based expiry and are only dropped
      under the final hard cap ``max_entries`` — oldest-first, so the most
      recent verified facts survive.
    - Entries with no usable timestamp count as recent and are never
      age-evicted.

    Returns ``(store, evicted_count)`` where *store* is a fresh
    ``{key: entry}`` dict (or list) without the evicted entries.
    """
    epoch = time.time() if now is None else now
    is_list = isinstance(store, list)
    pairs = (
        [(str(i), entry) for i, entry in enumerate(store)]
        if is_list else list(store.items())
    )
    kept: List[tuple] = []
    evicted = 0
    for key, entry in pairs:
        ts, verified = _entry_meta(entry)
        if not verified and ts:
            age_days = (epoch - ts) / 86400.0
            if age_days > max_age_days:
                evicted += 1
                continue
        kept.append((ts, verified, key, entry))
    if len(kept) > max_entries:
        kept.sort(key=lambda item: (item[1], item[0], item[2]))
        evicted += len(kept) - max_entries
        kept = kept[len(kept) - max_entries:]
    if is_list:
        return [entry for _ts, _ver, _k, entry in kept], evicted
    return {key: entry for _ts, _ver, key, entry in kept}, evicted


@dataclass
class MemoryContext:
    """Aggregated memory context for a single turn."""
    session_history: str = ""
    rag_context: str = ""
    failure_vaccines: str = ""
    knowledge_context: str = ""
    episodic: str = ""
    working: str = ""
    semantic: str = ""
    procedural: str = ""

    def as_text(self) -> str:
        parts = []
        if self.session_history:
            parts.append(f"[SESSION]:\n{self.session_history}")
        if self.rag_context:
            parts.append(f"[RAG]:\n{self.rag_context}")
        if self.failure_vaccines:
            parts.append(f"[FAILURES]:\n{self.failure_vaccines}")
        if self.knowledge_context:
            parts.append(f"[KNOWLEDGE]:\n{self.knowledge_context}")
        if self.episodic:
            parts.append(f"[EPISODIC]:\n{self.episodic}")
        if self.working:
            parts.append(f"[WORKING]:\n{self.working}")
        if self.semantic:
            parts.append(f"[SEMANTIC]:\n{self.semantic}")
        if self.procedural:
            parts.append(f"[PROCEDURAL]:\n{self.procedural}")
        return _sanitize_recalled_text("\n\n".join(parts))


class MemoryManager:
    """Unified memory orchestrator — wraps all NEXUS memory systems.

    Usage:
        memory = MemoryManager(root_dir)
        ctx = await memory.prefetch_all(user_msg)
        # ... run model/tools (collect verified tool evidence) ...
        await memory.sync_all(user_msg, response, verified_actions=acts, tool_results=results)
    """

    def __init__(
        self,
        root_dir: str,
        session_id: str = "",
        max_session_lines: int = 12,
    ) -> None:
        self.root = os.path.abspath(root_dir)
        if session_id:
            self.session_id = safe_session_id(session_id)
        else:
            # Default to the most-recently-modified session file so a fresh process
            # resumes the real conversation instead of inventing a random id that
            # can never be looked up (which made NEXUS "forget everything").
            self.session_id = self._resolve_latest_session_id()
        self.max_session_lines = max_session_lines
        self._memory: List[Dict[str, str]] = []
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._opencode_memory_dir = os.path.join(self.root, ".opencode", "memory")
        self._in_memory: Dict[str, str] = {}  # key -> text

    def continuity(self):
        """Return unfinished persisted work, if explicit evidence exists."""
        # Queue state is durable evidence too.  Keep the queue object local so
        # continuity remains a read-only snapshot and does not create a long-
        # lived worker/connection owned by MemoryManager.
        queue = None
        try:
            from queue.store import TaskQueue

            queue = TaskQueue(root=self.root)
        except Exception:
            queue = None
        return inspect_continuity(self.root, self.session_id, queue=queue)

    @staticmethod
    def _resolve_latest_session_id(root: Optional[str] = None) -> str:
        """Pick the most-recently-modified session file so a fresh process resumes
        the real conversation instead of inventing an unresolvable random id."""
        if root:
            root = os.path.abspath(root)
            # Prefer unfinished run-context/checkpoint evidence over a newer
            # completed transcript.  This is what lets a fresh process resume
            # the task that was interrupted instead of starting a new chat.
            candidates = []
            contexts = os.path.join(root, "logs", "run_contexts")
            if os.path.isdir(contexts):
                for session in os.listdir(contexts):
                    folder = os.path.join(contexts, session)
                    if not os.path.isdir(folder):
                        continue
                    for name in os.listdir(folder):
                        if not name.endswith(".json"):
                            continue
                        try:
                            with open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
                                record = json.load(handle)
                            if str(record.get("status", "")).lower() in {"running", "failed", "error", "cancelled", "canceled", "aborted"}:
                                candidates.append((float(record.get("updated_at") or record.get("started_at") or 0), session))
                        except (OSError, ValueError, TypeError):
                            continue
            checkpoints = os.path.join(root, ".nexus_v5", "checkpoints")
            if os.path.isdir(checkpoints):
                terminal = {"complete", "completed", "done", "success", "succeeded", "finished"}
                for name in os.listdir(checkpoints):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(checkpoints, name)
                    try:
                        with open(path, "r", encoding="utf-8") as handle:
                            record = json.load(handle)
                        phase = str(record.get("phase") or "").strip().lower()
                        session = str(record.get("session") or record.get("session_id") or "").strip()
                        if session and phase not in terminal:
                            candidates.append((float(record.get("ts") or os.path.getmtime(path)), session))
                    except (OSError, ValueError, TypeError):
                        continue
            queue_db = os.path.join(root, ".nexus_queue.db")
            if os.path.exists(queue_db):
                try:
                    conn = sqlite3.connect(queue_db)
                    rows = conn.execute("SELECT payload, updated_at FROM tasks WHERE state IN ('queued','leased','retrying','failed')").fetchall()
                    conn.close()
                    for payload_text, updated_at in rows:
                        payload = json.loads(payload_text or "{}")
                        meta = payload.get("meta") if isinstance(payload, dict) else {}
                        session = str((meta or {}).get("session_id") or "").strip()
                        if session:
                            candidates.append((float(updated_at or 0), session))
                except (OSError, sqlite3.Error, ValueError, TypeError):
                    pass
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]

            queue_db = os.path.join(root, ".nexus_queue.db")
            if os.path.isfile(queue_db):
                try:
                    connection = sqlite3.connect(queue_db)
                    rows = connection.execute(
                        "SELECT payload, updated_at FROM tasks WHERE state IN ('queued','leased','retrying') ORDER BY updated_at DESC"
                    ).fetchall()
                    connection.close()
                    for payload_text, updated_at in rows:
                        payload = json.loads(payload_text or "{}")
                        meta = payload.get("meta") if isinstance(payload, dict) else {}
                        session = str((meta or {}).get("session_id") or "").strip()
                        if session:
                            candidates.append((_timestamp(updated_at), session))
                except (OSError, sqlite3.Error, ValueError, TypeError):
                    pass
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]

            checkpoint_dir = os.path.join(root, ".nexus_v5", "checkpoints")
            if os.path.isdir(checkpoint_dir):
                for name in os.listdir(checkpoint_dir):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(checkpoint_dir, name)
                    try:
                        with open(path, "r", encoding="utf-8") as handle:
                            record = json.load(handle)
                        phase = str(record.get("phase") or "").lower()
                        session = str(record.get("session") or "").strip()
                        if session and phase not in {"complete", "completed", "done", "success", "succeeded", "finished"}:
                            candidates.append((_timestamp(record.get("ts"), os.path.getmtime(path)), session))
                    except (OSError, ValueError, TypeError):
                        continue
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]

            sess_dir = os.path.join(root, "logs", "sessions")
            if os.path.isdir(sess_dir):
                try:
                    files = [
                        os.path.join(sess_dir, f)
                        for f in os.listdir(sess_dir)
                        if f.endswith(".json") and not f.startswith(".")
                    ]
                    if files:
                        latest = max(files, key=os.path.getmtime)
                        return os.path.splitext(os.path.basename(latest))[0]
                except Exception:
                    pass
        return f"session_{uuid.uuid4().hex[:8]}"

    # ─── Public API ───────────────────────────────────────────────────

    async def prefetch_all(self, user_message: str) -> MemoryContext:
        """Pre-turn: load all memory sources relevant to *user_message*.

        Runs session memory load + RAG retrieval + failure memory + knowledge
        in parallel via thread pool.
        """
        ctx = MemoryContext()

        tasks = [
            self._prefetch_session,
            self._prefetch_rag,
            self._prefetch_failures,
            self._prefetch_knowledge,
        ]

        import asyncio
        results = await asyncio.gather(
            *[asyncio.to_thread(t, user_message) for t in tasks],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Memory prefetch error: {result}")

        ctx.session_history = results[0] if not isinstance(results[0], Exception) else ""
        ctx.rag_context = results[1] if not isinstance(results[1], Exception) else ""
        ctx.failure_vaccines = results[2] if not isinstance(results[2], Exception) else ""
        ctx.knowledge_context = results[3] if not isinstance(results[3], Exception) else ""

        try:
            await asyncio.to_thread(
                self._prefetch_episodic, user_message=user_message
            )
            await asyncio.to_thread(self._prefetch_procedural, user_message)
            ctx.episodic = self._in_memory.get("episodic", "")
            ctx.working = self._in_memory.get("working", "")
            ctx.semantic = self._in_memory.get("semantic", "")
            ctx.procedural = self._in_memory.get("procedural", "")
        except Exception as e:
            logger.debug(f"Memory episodic prefetch error: {e}")

        return ctx

    async def sync_all(
        self,
        user_message: str,
        response: str,
        verified_actions: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        verified: Optional[bool] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Post-turn: persist memory and extract verified learnings.

        Only *verified* tool evidence is ever written to the durable fact
        sinks (.opencode/memory/ files and the evolution memory forge). Raw
        model prose is kept in the session transcript as a conversation
        record, tagged ``verified: False`` so ``_prefetch_session`` recall
        does not surface unverified claims as ground truth.

        ``verified_actions`` / ``tool_results`` carry the real, already-verified
        tool evidence from the run; ``verified`` is the overall verdict. All
        three default to falsy so existing callers keep working (they simply
        persist a transcript record and no fabricated cross-session learnings).
        """
        import asyncio

        actions = list(verified_actions or [])
        if verified is None:
            verified = bool(actions) and all(
                isinstance(a, dict) and a.get("verified", a.get("success", False))
                for a in actions
            )

        tasks = [
            asyncio.to_thread(self._sync_session, user_message, response, verified),
            asyncio.to_thread(
                self._sync_opencode_memory,
                user_message,
                response,
                actions,
                list(tool_results or []),
                verified,
                dict(provenance or {}),
            ),
        ]

        # Kick off memory forge in background, gated on verified evidence.
        try:
            from evolution.memory_forge.scripts.forge import MemoryForge
            forge = MemoryForge(self.root)
            if verified and tool_results:
                evidence = _tool_evidence_text(tool_results, limit=500)
                if evidence:
                    tasks.append(
                        asyncio.to_thread(
                            forge.forge,
                            f"session_{self.session_id}",
                            f"Verified: {evidence}"
                        )
                    )
        except Exception:
            logger.warning("memory/__init__.py:129 : suppressed error", exc_info=True)
            pass

        await asyncio.gather(*tasks, return_exceptions=True)

    def _persist_memory_evidence(
        self,
        tool_results: List[Dict[str, Any]],
        provenance: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Persist redacted, deduplicated provenance for verified tool facts."""
        if not tool_results:
            return []
        base = {
            key: _sanitize_recalled_text(value)[:500]
            for key, value in (provenance or {}).items()
            if key in {"session_id", "turn_id", "task_id", "provider_run_evidence_path", "provider", "profile", "model"}
        }
        path = os.path.join(self.root, _MEMORY_EVIDENCE_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        records: List[Dict[str, Any]] = []
        ids: List[str] = []
        with _MEMORY_EVIDENCE_LOCK:
            existing = set()
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as stream:
                        for line in stream:
                            try:
                                item = json.loads(line)
                                if item.get("memory_id"):
                                    existing.add(str(item["memory_id"]))
                            except Exception:
                                continue
                except OSError:
                    pass
            for result in tool_results:
                if not isinstance(result, dict):
                    continue
                tool = _sanitize_recalled_text(result.get("tool") or result.get("name") or "tool")[:120]
                call_id = _sanitize_recalled_text(result.get("call_id") or "")[:160]
                summary = _sanitize_recalled_text(_tool_evidence_text([result], limit=300))
                digest_input = json.dumps({**base, "tool": tool, "call_id": call_id, "summary": summary}, sort_keys=True)
                memory_id = "mem-" + hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:20]
                ids.append(memory_id)
                if memory_id in existing:
                    continue
                record = {
                    "memory_id": memory_id,
                    "created_at": time.time(),
                    "provenance": base,
                    "tool": tool,
                    "call_id": call_id,
                    "verified": bool(result.get("verified", result.get("success", False))),
                    "summary": summary,
                    "result_digest": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                }
                records.append(record)
            if records:
                with open(path, "a", encoding="utf-8") as stream:
                    for record in records:
                        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return ids

    def shutdown(self, timeout: int = 5) -> None:
        """Shutdown thread pool — drain in-flight work."""
        self._pool.shutdown(wait=True)
        self._pool._threads.clear() if hasattr(self._pool, "_threads") else None

    # ─── In-memory access ────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        """Get a flat memory value by key (episodic, working, etc.)."""
        return self._in_memory.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set a flat memory value."""
        self._in_memory[key] = value

    def summary(self) -> str:
        """Return a compact summary of all in-memory values for system prompt."""
        parts = []
        for key in ("episodic", "working", "semantic", "procedural"):
            val = self._in_memory.get(key, "")
            if val:
                val_trimmed = val[:200].replace("\n", " ")
                parts.append(f"{key}: {val_trimmed}")
        return "\n".join(parts)

    def get_statistics(self) -> Dict[str, Any]:
        """Return comprehensive memory statistics."""
        stats = {
            "session_id": self.session_id,
            "in_memory_keys": list(self._in_memory.keys()),
            "in_memory_size": sum(len(v) for v in self._in_memory.values()),
            "session_history_length": len(self._memory),
            "max_session_lines": self.max_session_lines,
        }
        
        # Add file-based statistics
        try:
            session_path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if os.path.exists(session_path):
                stats["session_file_size"] = os.path.getsize(session_path)
                stats["session_file_modified"] = os.path.getmtime(session_path)
            
            # Count session files
            sess_dir = os.path.join(self.root, "logs", "sessions")
            if os.path.isdir(sess_dir):
                session_files = [f for f in os.listdir(sess_dir) if f.endswith(".json")]
                stats["total_sessions"] = len(session_files)
        except Exception:
            pass
        
        return stats

    def export_memory(self, format: str = "json") -> str:
        """Export all memory data to a string."""
        export_data = {
            "session_id": self.session_id,
            "in_memory": self._in_memory,
            "session_history": self._memory,
            "statistics": self.get_statistics(),
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        if format == "json":
            return json.dumps(export_data, indent=2)
        elif format == "text":
            lines = [
                f"NEXUS Memory Export - {self.session_id}",
                f"Exported: {export_data['exported_at']}",
                "",
                "=== In-Memory ===",
            ]
            for key, value in self._in_memory.items():
                lines.append(f"{key}: {value[:200]}")
            lines.append("")
            lines.append("=== Session History ===")
            for item in self._memory[-10:]:  # Last 10 items
                role = item.get("role", "unknown")
                content = item.get("content", "")[:100]
                lines.append(f"{role}: {content}")
            return "\n".join(lines)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def import_memory(self, data: str, format: str = "json") -> bool:
        """Import memory data from a string."""
        try:
            if format == "json":
                import_data = json.loads(data)
                if isinstance(import_data, dict) and "in_memory" in import_data:
                    self._in_memory.update(import_data.get("in_memory", {}))
                if isinstance(import_data, dict) and "session_history" in import_data:
                    self._memory.extend(import_data.get("session_history", []))
                return True
            return False
        except Exception as e:
            logger.error(f"Memory import failed: {e}")
            return False

    def clear_memory(self, memory_type: str = "all") -> None:
        """Clear specific or all memory types."""
        if memory_type == "all":
            self._in_memory.clear()
            self._memory.clear()
        elif memory_type == "in_memory":
            self._in_memory.clear()
        elif memory_type == "session":
            self._memory.clear()
        elif memory_type in self._in_memory:
            del self._in_memory[memory_type]

    def search_memory(self, query: str, memory_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search across all memory types for a query."""
        results = []
        types_to_search = memory_types or list(self._in_memory.keys()) + ["session"]
        
        for mem_type in types_to_search:
            if mem_type == "session":
                for item in self._memory:
                    content = item.get("content", "")
                    if query.lower() in content.lower():
                        results.append({
                            "type": "session",
                            "role": item.get("role"),
                            "content": content[:200],
                            "match_position": content.lower().find(query.lower()),
                        })
            elif mem_type in self._in_memory:
                content = self._in_memory[mem_type]
                if query.lower() in content.lower():
                    results.append({
                        "type": mem_type,
                        "content": content[:200],
                        "match_position": content.lower().find(query.lower()),
                    })
        
        return results

    def set_retention_policy(self, policy: Dict[str, Any]) -> None:
        """Set memory retention policies."""
        self._retention_policy = policy

    def apply_retention_policy(self) -> None:
        """Apply retention policies to clean up old memory."""
        if not hasattr(self, "_retention_policy"):
            return
        
        policy = self._retention_policy
        
        # Trim session history if needed
        max_items = policy.get("max_session_items", 100)
        if len(self._memory) > max_items:
            self._memory = self._memory[-max_items:]
        
        # Clear old in-memory entries
        if policy.get("clear_in_memory_on_shutdown", False):
            self._in_memory.clear()

    # ─── Session memory ──────────────────────────────────────────────

    def _prefetch_session(self, user_message: str) -> str:
        """Load last N turns from session JSON."""
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path):
                path = os.path.join(self.root, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    lines = []
                    for m in data[-self.max_session_lines:]:
                        role = m.get("role", "")
                        content = m.get("content", "")
                        if role not in ("user", "assistant"):
                            continue
                        # Unverified assistant claims are a conversation record,
                        # not ground truth — never surface them back as recalled
                        # context.  Legacy entries (no ``verified`` key) and
                        # verified entries still recall normally.
                        if role == "assistant" and m.get("verified") is False:
                            continue
                        clean = content.split("\n\n[VOICE_MODE]:")[0].split("[VOICE_MODE]:")[0]
                        clean = clean.strip()[:200]
                        lines.append(f"{role.upper()}: {clean}")
                    history = "\n".join(lines)
                    continuity = self.continuity().as_prompt()
                    return "\n".join(part for part in (history, continuity) if part)
        except Exception:
            logger.warning("memory/__init__.py:180 _prefetch_session: suppressed error", exc_info=True)
            pass
        return self.continuity().as_prompt()

    def _sync_session(self, user_message: str, response: str, verified: bool = False) -> None:
        """Append to session history and persist.

        Seeds from the existing on-disk history first so a fresh process does not
        truncate the session file to only its own turns (the loop also writes this
        same file via _write_session_bus — this merge avoids clobbering it).

        Assistant text is tagged ``verified: False`` when no verified tool
        evidence backs it, so the record is kept but never recalled as ground
        truth by ``_prefetch_session``.
        """
        if not user_message and not response:
            return
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Serialize writers and replace atomically.  A direct ``open(...,
            # 'w')`` can leave a truncated session after a crash and concurrent
            # MemoryManager instances can otherwise overwrite each other's
            # merged history.
            from nexus.session_store import atomic_write_json, session_write_lock
            with session_write_lock(path):
                # Hold the lock across read/merge/write.  Locking only the
                # final replace still permits two processes to read the same
                # old snapshot and lose one turn.
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as fh:
                            existing = json.load(fh)
                        if isinstance(existing, list):
                            have = {
                                (m.get("role"), m.get("content"))
                                for m in self._memory
                                if isinstance(m, dict)
                            }
                            for m in existing:
                                if isinstance(m, dict) and (m.get("role"), m.get("content")) not in have:
                                    self._memory.append(m)
                    except Exception:
                        logger.debug("session merge failed for %s", self.session_id, exc_info=True)
                if user_message:
                    self._memory.append({"role": "user", "content": user_message})
                if response:
                    self._memory.append({"role": "assistant", "content": response, "verified": verified})
                atomic_write_json(path, self._memory)
        except Exception as e:
            logger.error(f"sync_session failed: {e}")

    # ─── RAG retrieval ───────────────────────────────────────────────

    def _prefetch_rag(self, user_message: str) -> str:
        """Retrieve RAG context for user message."""
        if not user_message:
            return ""
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel()
            result = kernel.rag.retrieve_as_text(user_message, top_k=3)
            if result and "No relevant" not in result:
                return result[:2000]
        except Exception:
            logger.warning("memory/__init__.py:212 _prefetch_rag: suppressed error", exc_info=True)
            pass
        return ""

    # ─── Failure memory ──────────────────────────────────────────────

    def _prefetch_failures(self, user_message: str) -> str:
        """Load recent failure records as preventive vaccines."""
        try:
            from sandbox.failure_memory import FailureMemory
            fm = FailureMemory(self.root)
            recent = fm.recent(limit=5)
            if recent:
                vaccines = []
                for r in recent:
                    v = r.get("vaccine", r.get("error", ""))
                    if v:
                        vaccines.append(v[:200])
                return "PREVENTIVE VACCINES:\n" + "\n".join(vaccines) if vaccines else ""
        except Exception:
            logger.warning("memory/__init__.py:231 _prefetch_failures: suppressed error", exc_info=True)
            pass
        return ""

    # ─── Knowledge vault ─────────────────────────────────────────────

    def _prefetch_knowledge(self, user_message: str) -> str:
        """Retrieve from knowledge vault (optional, degrades gracefully)."""
        try:
            from knowledge.vault import KnowledgeVault
            vault = KnowledgeVault()
            result = vault.retrieve_as_text(user_message or "general", top_k=2)
            return result if result else ""
        except ImportError:
            logger.debug("Knowledge vault not available (optional module)")
        except Exception:
            logger.debug("_prefetch_knowledge: suppressed error", exc_info=True)
        return ""

    # ─── Episodic memory ─────────────────────────────────────────────

    def _prefetch_episodic(
        self, limit: int = 5, user_message: str = ""
    ) -> List[Dict[str, Any]]:
        """Load the top ``limit`` replay entries relevant to *user_message*.

        Reads ``<root>/.nexus_v5/replays.jsonl`` (written by the V5 loop's
        turn replay). Query coverage is the primary ranking key when a user
        message is supplied; the existing recency/importance score breaks
        ties. Without a query, the historical score-only ordering is kept.
        Stores a text digest in the ``episodic`` in-memory slot (surfaced by
        ``summary()``) and returns the digest list. Never raises; [] on any
        failure.
        """
        digests: List[Dict[str, Any]] = []
        try:
            path = os.path.join(self.root, _REPLAY_FILE_REL)
            if not os.path.isfile(path):
                return digests
            entries: List[Dict[str, Any]] = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        entries.append(parsed)
            now = time.time()
            query = str(user_message or "").strip()
            if query:
                scored = sorted(
                    entries,
                    key=lambda entry: (
                        _episodic_query_relevance(entry, query),
                        _episodic_score_entry(entry, now),
                    ),
                    reverse=True,
                )
            else:
                scored = sorted(
                    entries,
                    key=lambda entry: _episodic_score_entry(entry, now),
                    reverse=True,
                )
            for entry in scored[: max(0, int(limit))]:
                digests.append({
                    "score": round(_episodic_score_entry(entry, now), 4),
                    "input": str(entry.get("input") or "")[:200],
                    "outcome": "failure" if _episodic_entry_failed(entry) else "success",
                    "ts": str(entry.get("timestamp") or ""),
                })
            if digests:
                lines = []
                for digest in digests:
                    lines.append(
                        f"[{digest['outcome']}] {digest['input'][:100]} "
                        f"(score {digest['score']:.2f})"
                    )
                self._in_memory["episodic"] = "\n".join(lines)
        except Exception as e:
            logger.warning("memory/__init__.py _prefetch_episodic: suppressed error: %s", e)
        return digests

    # ─── Procedural memory (skills) ──────────────────────────────────

    def _prefetch_procedural(self, user_message: str = "", limit: int = 3) -> str:
        """Rank the durable skill corpus against *user_message*.

        Skills (written by evolution/skill_forge and shipped under
        ``skills/``) are NEXUS's procedural memory. ``MemoryContext.procedural``
        is already consumed by the V5 turn pipeline, but nothing populated it,
        so the corpus was write-only. This fills the ``procedural`` in-memory
        slot with a bounded digest of the top-ranked skills. Never raises;
        returns "" on any failure.
        """
        try:
            from skills.engine import NexusSkillEngine

            engine = NexusSkillEngine(self.root)
            selected = engine.select_skills(user_message or "", limit=limit) or []
            lines = []
            for skill in selected[: max(0, int(limit))]:
                name = str(getattr(skill, "name", "") or getattr(skill, "id", "")).strip()
                if not name:
                    continue
                desc = str(getattr(skill, "description", "") or "").strip()
                lines.append(f"- {name}: {desc[:200]}" if desc else f"- {name}")
            digest = "\n".join(lines)[:2000]
            if digest:
                self._in_memory["procedural"] = digest
            return digest
        except Exception:
            logger.debug("_prefetch_procedural: suppressed error", exc_info=True)
            return ""

    # ─── .opencode/memory/ sync ──────────────────────────────────────

    def _sync_opencode_memory(
        self,
        user_message: str,
        response: str,
        verified_actions: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        verified: bool = False,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Sync verified tool learnings to .opencode/memory/ files (cross-session).

        Gated on verified evidence: only all-verified, non-empty tool results
        are written as cross-session learnings, and the persisted digest is the
        tool's real output/status — never unverified raw model prose.
        """
        if not verified or not tool_results:
            return
        try:
            memory_ids = self._persist_memory_evidence(tool_results, provenance)
            learned_path = os.path.join(self._opencode_memory_dir, "learned.md")
            if not os.path.isfile(learned_path):
                return
            # Append a brief learning entry from the verified tool evidence
            summary = _tool_evidence_text(tool_results, limit=300)
            if not summary:
                return
            refs = f" [{', '.join(memory_ids)}]" if memory_ids else ""
            if refs:
                try:
                    with open(learned_path, "r", encoding="utf-8") as f:
                        existing_text = f.read()
                    if any(memory_id in existing_text for memory_id in memory_ids):
                        return
                except OSError:
                    pass
            entry = f"- {time.strftime('%Y-%m-%d %H:%M')}: {summary}{refs}\n"
            with open(learned_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.debug(f"sync_opencode_memory failed: {e}")
