"""Unified MemoryManager — central orchestrator for all NEXUS memory systems.

Provides a single ``prefetch_all(user_msg)`` / ``sync_all(user_msg, response)``
API that wraps session memory, failure memory, RAG, knowledge vault, evolution
memory forge, and .opencode/memory/ files (Hermes-inspired architecture).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus.memory")


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
        return "\n\n".join(parts)


class MemoryManager:
    """Unified memory orchestrator — wraps all NEXUS memory systems.

    Usage:
        memory = MemoryManager(root_dir)
        ctx = await memory.prefetch_all(user_msg)
        # ... run model/tools ...
        await memory.sync_all(user_msg, response)
    """

    def __init__(
        self,
        root_dir: str,
        session_id: str = "",
        max_session_lines: int = 6,
    ) -> None:
        self.root = os.path.abspath(root_dir)
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_session_lines = max_session_lines
        self._memory: List[Dict[str, str]] = []
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._opencode_memory_dir = os.path.join(self.root, ".opencode", "memory")
        self._in_memory: Dict[str, str] = {}  # key -> text

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

        return ctx

    async def sync_all(self, user_message: str, response: str) -> None:
        """Post-turn: persist memory and extract learnings.

        Saves session history, syncs to .opencode/memory/ files,
        records to evolution memory forge (async).
        """
        import asyncio

        tasks = [
            asyncio.to_thread(self._sync_session, user_message, response),
            asyncio.to_thread(self._sync_opencode_memory, user_message, response),
        ]

        # Kick off memory forge in background
        try:
            from evolution.memory_forge.scripts.forge import MemoryForge
            forge = MemoryForge(self.root)
            if response and len(response) > 100:
                tasks.append(
                    asyncio.to_thread(
                        forge.forge,
                        f"session_{self.session_id}",
                        f"Learning: {response[:500]}"
                    )
                )
        except Exception:
            logger.warning("memory/__init__.py:129 : suppressed error", exc_info=True)
            pass

        await asyncio.gather(*tasks, return_exceptions=True)

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
                        if role in ("user", "assistant"):
                            clean = content.split("\n\n[VOICE_MODE]:")[0].split("[VOICE_MODE]:")[0]
                            clean = clean.strip()[:200]
                            lines.append(f"{role.upper()}: {clean}")
                    return "\n".join(lines)
        except Exception:
            logger.warning("memory/__init__.py:180 _prefetch_session: suppressed error", exc_info=True)
            pass
        return ""

    def _sync_session(self, user_message: str, response: str) -> None:
        """Append to session history and persist."""
        if not user_message and not response:
            return
        try:
            if user_message:
                self._memory.append({"role": "user", "content": user_message})
            if response:
                self._memory.append({"role": "assistant", "content": response})
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, indent=2)
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
        """Retrieve from knowledge vault."""
        try:
            from knowledge.vault import KnowledgeVault
            vault = KnowledgeVault()
            result = vault.retrieve_as_text(user_message or "general", top_k=2)
            return result if result else ""
        except Exception:
            logger.warning("memory/__init__.py:244 _prefetch_knowledge: suppressed error", exc_info=True)
            pass
        return ""

    # ─── .opencode/memory/ sync ──────────────────────────────────────

    def _sync_opencode_memory(self, user_message: str, response: str) -> None:
        """Sync key learnings to .opencode/memory/ files (cross-session)."""
        if not response or not user_message:
            return
        try:
            learned_path = os.path.join(self._opencode_memory_dir, "learned.md")
            if not os.path.isfile(learned_path):
                return
            # Append a brief learning entry
            summary = response.strip()[:300].replace("\n", " ")
            entry = f"- {time.strftime('%Y-%m-%d %H:%M')}: {summary}\n"
            with open(learned_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.debug(f"sync_opencode_memory failed: {e}")
