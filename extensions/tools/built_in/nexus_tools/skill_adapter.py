"""Skill Tool Adapter — bridges NEXUS skills into the ToolRegistry.

Skills defined via SKILL.md format can be invoked as tools through
the same execute/stream_execute pipeline.

Skills are implemented as LLM-guided operations: the skill prompt
is fed to the model which then generates tool calls to fulfill the skill.

The adapter returns the skill's *actual* instruction block (frontmatter name,
description, tags plus the body), not a placeholder marker, so a model invoking
a skill as a tool gets the full re-usable guidance inside the ToolResult
envelope.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult
from extensions.tools.built_in.nexus_tools.result import STATUS_ERROR, STATUS_OK, ToolCallResult, classify_error

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)


def parse_skill_md(content: str) -> Dict[str, Any]:
    """Parse a SKILL.md document into ``{name, description, tags, prompt}``.

    Single source both the adapter and the engine use for building an
    instruction block from a SKILL.md file. Pure stdlib, never raises.
    """
    import yaml  # local import: the adapter must stay loadable without yaml

    result: Dict[str, Any] = {"name": "", "description": "", "tags": [], "prompt": ""}
    body = content.strip()
    match = _FRONTMATTER_RE.match(content)
    meta: Dict[str, Any] = {}
    if match:
        frontmatter_text = match.group(1)
        body = match.group(2).strip()
        try:
            fm = yaml.safe_load(frontmatter_text) or {}
            if isinstance(fm, dict):
                meta = fm
        except Exception:
            for line in frontmatter_text.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip().lower()] = val.strip().strip("\"'")

    name = str(meta.get("name") or meta.get("id") or "").strip().strip("\"'")
    description = str(meta.get("description", "")).strip().strip("\"'")

    tags: list = []
    raw_tags = meta.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(t).strip().strip("\"'") for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.replace("[", "").replace("]", "").split(",") if t.strip()]
    if not tags:
        # Nested convention: metadata: {hermes: {tags: [...]}}
        nested = meta.get("metadata")
        if isinstance(nested, dict):
            for _kv in nested.values():
                if isinstance(_kv, dict) and _kv.get("tags"):
                    sub = _kv["tags"]
                    if isinstance(sub, list):
                        tags.extend(str(t).strip() for t in sub if str(t).strip())
                    elif isinstance(sub, str):
                        tags.extend(t.strip() for t in sub.replace("[", "").replace("]", "").split(",") if t.strip())
    seen = set()
    deduped = []
    for t in tags:
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    result.update({"name": name, "description": description, "tags": deduped, "prompt": body})
    return result


def build_instruction_block(name: str, skill_prompt: str, parsed: Optional[Dict[str, Any]] = None) -> str:
    """Compose the instruction block injected when a skill is invoked as a tool."""
    if parsed:
        lines = [f"Skill: {parsed.get('name') or name}"]
        desc = parsed.get("description") or ""
        if desc:
            lines.append(f"Description: {desc}")
        if parsed.get("tags"):
            lines.append("Tags: " + ", ".join(parsed["tags"]))
        lines.append("")
        lines.append("Instructions:")
        lines.append(parsed.get("prompt", "") or skill_prompt)
        return "\n".join(lines)
    if skill_prompt:
        return f"Skill: {name}\n\nInstructions:\n{skill_prompt}"
    return f"[SKILL_ACTIVE: {name}]"


class SkillToolAdapter(BaseTool):
    """Adapts a NEXUS skill into a BaseTool for the ToolRegistry.

    Skills differ from regular tools in that they don't have a direct
    handler — instead, they inject a skill prompt into the agent context.
    This adapter provides a tool interface so skills appear in tool lists
    and can be dispatched uniformly.

    ``skill_path`` may point at the SKILL.md directly; when present the
    execute() result is built from the parsed frontmatter + body so the model
    receives the skill's real instructions (not just a ``[SKILL_ACTIVE]``
    marker). ``skill_prompt`` remains the fallback for callers that already
    pre-resolved the prompt (fully backward compatible).
    """

    def __init__(
        self,
        name: str,
        skill_prompt: str = "",
        description: str = "",
        root_dir: Optional[str] = None,
        skill_path: Optional[str] = None,
    ) -> None:
        super().__init__(root_dir)
        self.name = name
        self.description = description or f"Skill: {name}"
        self.skill_prompt = skill_prompt
        self.skill_path = skill_path
        self._parsed: Optional[Dict[str, Any]] = None
        if skill_path and os.path.isfile(skill_path):
            try:
                self._parsed = parse_skill_md(_read_skill(skill_path))
            except Exception:
                logging.getLogger(__name__).warning("Failed to parse skill: %s", skill_path, exc_info=True)

    def instruction_block(self) -> str:
        """Build the full instruction block returned when this skill is invoked."""
        return build_instruction_block(self.name, self.skill_prompt, self._parsed)

    async def execute(self, **kwargs) -> ToolResult:
        """Return the skill's real instructions for the agent loop to inject."""
        instructions = self.instruction_block()
        metadata: Dict[str, Any] = {
            "skill_name": self.name,
            "type": "skill_prompt",
            "skill_path": self.skill_path or "",
        }
        if self._parsed:
            metadata.update(
                {
                    "description": self._parsed.get("description", ""),
                    "tags": list(self._parsed.get("tags", [])),
                }
            )
        return ToolCallResult(name=self.name, status=STATUS_OK, output=instructions, metadata=metadata)

    async def stream_execute(self, **kwargs):
        """Stream the skill prompt."""
        result = await self.execute(**kwargs)
        yield result

    def is_read_only(self, params=None) -> bool:
        """Skills are read-only tools that inject context."""
        return True


class SkillExecutor(BaseTool):
    """Full skill execution via LLM-guided tool orchestration.

    Requires an llm_call function that takes the skill prompt + user args
    and returns the model's response (which may include tool calls).
    """

    def __init__(
        self,
        name: str,
        skill_prompt: str,
        llm_call: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        root_dir: Optional[str] = None,
    ) -> None:
        super().__init__(root_dir)
        self.name = name
        self.skill_prompt = skill_prompt
        self._llm_call = llm_call
        self._tool_registry = tool_registry

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the skill by invoking the LLM with the skill prompt."""
        if not self._llm_call:
            return ToolCallResult(
                name=self.name,
                status=STATUS_OK,
                output=f"[SKILL_ACTIVE: {self.name}]\n{self.skill_prompt}",
            )
        user_args = kwargs.get("args", "")
        full_prompt = f"{self.skill_prompt}\n\nUser request: {user_args}" if user_args else self.skill_prompt
        try:
            result = await self._llm_call(full_prompt)
            return ToolCallResult(name=self.name, status=STATUS_OK, output=str(result))
        except Exception as exc:
            return ToolCallResult(
                name=self.name,
                status=STATUS_ERROR,
                error=str(exc) or type(exc).__name__,
                error_info=classify_error(exc),
                metadata={"skill_name": self.name, "execution_failed": True},
            )

    def is_read_only(self, params=None) -> bool:
        return True


def _read_skill(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""
