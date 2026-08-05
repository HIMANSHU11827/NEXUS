"""V5ContextGrounding — workspace context loading for V5 loop.

Ports V1's _ground_context: stable identity, rules, project docs,
knowledge (RAG), workstyle, prompt files, tool descriptions.
"""

from __future__ import annotations

import asyncio, logging, os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class V5ContextGrounding:
    """Mixin providing workspace-aware context grounding."""

    def _build_stable_prompt(self) -> str:
        if getattr(self, "_stable_prompt_built", False) and self._stable_prompt_cache:
            return self._stable_prompt_cache
        parts: List[str] = []
        loader = getattr(self, "_load_soul_md", None)
        if callable(loader):
            soul = loader()
            if soul:
                parts.append(soul)
        tools_desc = self._load_tool_descriptions()
        if tools_desc:
            parts.append(tools_desc)
        try:
            from skills.engine import NexusSkillEngine
            engine = NexusSkillEngine(); skills = engine.list_skills()
        except ImportError:
            try:
                from skills import NexusSkillMaster
                master = NexusSkillMaster(self.root_dir)
                skills = master.list_skills()
            except Exception:
                skills = []
        except Exception:
            skills = []
        if skills:
            lines = ["# SKILLS INDEX:"]
            for s in skills:
                name = s.get("name", s.get("id", "?"))
                desc = s.get("description", "")
                lines.append(f"  /{name}: {desc}" if desc else f"  /{name}")
            parts.append("\n".join(lines))
        result = "\n\n".join(parts)
        self._stable_prompt_cache = result
        self._stable_prompt_built = True
        return result

    def _load_tool_descriptions(self) -> str:
        registry = getattr(self, "tool_registry", None)
        if registry is None:
            return ""
        try:
            lines = ["[AVAILABLE TOOLS]"]
            for name in sorted(registry.list_tools()):
                entry = registry.get(name)
                if entry and entry.schema:
                    desc = entry.schema.get("description", "")
                    lines.append(f"- {name}: {desc}" if desc else f"- {name}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _load_continuity_context(self) -> str:
        """Return persisted unfinished-work evidence for the active session."""
        manager = getattr(self, "_memory_manager", None)
        continuity = getattr(manager, "continuity", None)
        if not callable(continuity):
            return ""
        try:
            snapshot = continuity()
            return snapshot.as_prompt() if getattr(snapshot, "available", False) else ""
        except Exception:
            return ""


    def _load_progressive_rules(self) -> str:
        patterns = ["AGENTS.md", "CLAUDE.md", ".cursorrules", "RULES.md",
                     ".github/AGENTS.md", ".github/CLAUDE.md"]
        parts: List[str] = []
        for pattern in patterns:
            fpath = os.path.join(self.root_dir, pattern)
            try:
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        parts.append(f"## {pattern}\n\n{content}")
            except OSError:
                pass
        return "\n\n".join(parts)

    def _load_project_docs(self) -> str:
        parts: List[str] = []
        for fname in ("README.md", "pyproject.toml"):
            fpath = os.path.join(self.root_dir, fname)
            try:
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()[:5000]
                    if content:
                        parts.append(f"## {fname}\n\n{content}")
            except OSError:
                pass
        return "\n\n".join(parts)

    def _load_knowledge_context(self, task_desc: str) -> str:
        rag = getattr(self, "rag", None)
        if rag is None:
            return ""
        try:
            results = rag.query(task_desc, top_k=3)
            if not results:
                return ""
            lines = ["## Knowledge Context"]
            for r in results:
                content = str(r.get("content", "") or "")[:500]
                if content:
                    lines.append(f"- {content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _workstyle_context(self, task_desc: str) -> str:
        p = os.path.join(self.root_dir, ".opencode", "workstyle.md")
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read().strip()[:2000]
        except Exception:
            pass
        return ""

    async def _ground_context(self, task_desc: str) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        needs = self._requires_real_tooling(task_desc)
        loader = getattr(self, "_build_stable_prompt", None)
        if callable(loader):
            try:
                stable = await asyncio.to_thread(loader)
                if stable:
                    messages.append({"role": "system", "content": stable[:8000]})
            except Exception:
                pass
        try:
            continuity = await asyncio.to_thread(self._load_continuity_context)
            if continuity:
                messages.append({"role": "system", "content": continuity[:3000]})
        except Exception:
            pass
        try:
            rules = await asyncio.to_thread(self._load_progressive_rules)
            if rules:
                messages.append({"role": "system", "content": rules[:3000]})
        except Exception:
            pass
        if needs:
            try:
                docs = await asyncio.to_thread(self._load_project_docs)
                if docs:
                    messages.append({"role": "system", "content": docs[:3000]})
            except Exception:
                pass
            try:
                kn = await asyncio.to_thread(self._load_knowledge_context, task_desc)
                if kn:
                    messages.append({"role": "system", "content": kn[:3000]})
            except Exception:
                pass
        try:
            ws = await asyncio.to_thread(self._workstyle_context, task_desc)
            if ws:
                messages.append({"role": "system", "content": ws[:2000]})
        except Exception:
            pass
        pf = getattr(self, "_load_prompt_files", None)
        if callable(pf):
            try:
                prompts = await asyncio.to_thread(pf)
                if prompts:
                    messages.append({"role": "system", "content": prompts[:3000]})
            except Exception:
                pass
        return messages

    def _requires_real_tooling(self, task_desc: str) -> bool:
        low = (task_desc or "").strip().lower()
        signals = (
            "file", "folder", "project", "repo", "codebase", "web",
            "latest", "live", "research", "inspect", "debug", "test",
            "run ", "execute", "fix", "edit", "install", "deploy",
            "delete", "create", "build", "make", "code", "implement",
            "refactor", "analyze", "review", "check", "generate",
            "design", "download", "upload", "configure", "setup",
            "publish", "remove", "rename", "move", "copy",
            "search code", "source code", "patch", "write code",
        )
        return any(sig in low for sig in signals)
