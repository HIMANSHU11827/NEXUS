"""V5Skill — skill integration for the V5 loop. V5: /skill-name
slash resolution (NexusSkillMaster + .opencode/skills fallback),
[SKILL_ACTIVE] injection, skills index for system context.
Activations emit a ``skill.activated`` runtime event and record a
use on the engine (feeding health + experience tracking).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

_SKILL_SLASH_RE = re.compile(r"^/([a-z0-9-]+)(?:\s+(.*))?$", re.IGNORECASE)


class V5Skill:
    """Mixin giving the V5 loop V5 skill integration.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.root`` - project root directory string used to locate the
      ``.opencode/skills/<name>/SKILL.md`` fallback and to construct the
      per-root ``NexusSkillMaster``.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self._emit_runtime_event`` - optional async runtime event emitter;
      skipped when absent or not callable.
    Perceived objects carry ``original_input`` (str) and
    ``context_summary`` (str, may be empty). Fully guarded: never raises.
    """

    def _skill_master(self):
        """Lazily return the per-root ``NexusSkillMaster`` or None.

        Imported inside the method (avoiding circular imports); the master
        is constructed once and cached on ``self._v5_skill_master``. Any
        failure - including a missing ``self.root`` - returns None and is
        retried on the next call. Never raises.
        """
        try:
            master = getattr(self, "_v5_skill_master", None)
            if master is None:
                try:
                    from skills.engine import NexusSkillEngine
                    master = NexusSkillEngine()
                except ImportError:
                    from skills import NexusSkillMaster
                    master = NexusSkillMaster(self.root)
                self._v5_skill_master = master
            return master
        except Exception:
            return None

    def _resolve_slash_skill(self, user_input: str) -> Optional[Dict[str, Any]]:
        """Resolve a leading ``/skill-name`` pattern to skill content.

        Only matches when the input starts with ``/`` at position 0 with no
        space before the skill word. Returns ``{"name", "prompt", "args"}``
        or None. Lookup order: the ``self._v5_slash_cache`` dict (lazily
        initialized), ``NexusSkillMaster.find_skill``, then the
        ``.opencode/skills/<name>/SKILL.md`` file fallback; prompts are
        capped at 2000 characters. Never raises.
        """
        try:
            if not user_input or not user_input.startswith("/"):
                return None
            match = _SKILL_SLASH_RE.match(user_input)
            if not match:
                return None
            name = match.group(1).lower()
            args = (match.group(2) or "").strip()
            cache = getattr(self, "_v5_slash_cache", None)
            if cache is None:
                cache = {}
                self._v5_slash_cache = cache
            if name in cache:
                return {"name": name, "prompt": cache[name], "args": args}
            master = self._skill_master()
            if master is not None:
                skill = master.find_skill(name)
                if skill and skill.get("prompt"):
                    prompt = str(skill["prompt"])[:2000]
                    cache[name] = prompt
                    return {"name": name, "prompt": prompt, "args": args}
            skill_path = os.path.join(self.root, ".opencode", "skills", name, "SKILL.md")
            if os.path.isfile(skill_path):
                try:
                    with open(skill_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(2000)
                except Exception:
                    content = ""
                if content and content.strip():
                    prompt = content[:2000]
                    cache[name] = prompt
                    return {"name": name, "prompt": prompt, "args": args}
            return None
        except Exception:
            return None

    async def _inject_skill_context(self, perceived) -> None:
        """Wire a resolved slash skill into the perceived input.

        Rewrites ``perceived.original_input`` to the remaining args (or the
        fallback ``Run the <name> skill.`` task), appends the
        ``[SKILL_ACTIVE: <name>]`` block to ``perceived.context_summary``
        (joined with a blank line when non-empty), and emits a
        ``skill.activated`` runtime event when an emitter is available.
        Never raises.
        """
        try:
            if perceived is None:
                return
            user_input = getattr(perceived, "original_input", None) or ""
            resolved = self._resolve_slash_skill(user_input)
            if not resolved:
                return
            try:
                perceived.original_input = (
                    resolved["args"] or f"Run the {resolved['name']} skill."
                )
            except Exception:
                pass
            master = self._skill_master()
            if master is not None:
                try:
                    record = getattr(master, "record_use", None)
                    if callable(record):
                        record(resolved["name"], success=True)
                except Exception:
                    pass
            block = f"[SKILL_ACTIVE: {resolved['name']}]\n{resolved['prompt']}"
            try:
                current = getattr(perceived, "context_summary", None)
                if current:
                    perceived.context_summary = f"{current}\n\n{block}"
                else:
                    perceived.context_summary = block
            except Exception:
                pass
            emitter = getattr(self, "_emit_runtime_event", None)
            if callable(emitter):
                turn_id = getattr(self, "_current_turn_id", "") or "run"
                try:
                    await emitter(
                        "skill.activated",
                        f"Skill {resolved['name']} activated",
                        "done",
                        event_id=f"skill_{resolved['name']}_{turn_id}",
                        payload={"name": resolved["name"]},
                    )
                except TypeError:
                    await emitter(
                        "skill.activated",
                        f"Skill {resolved['name']} activated",
                        "done",
                        payload={"name": resolved["name"]},
                    )
            lc_mark = getattr(self, "_lifecycle_mark", None)
            if callable(lc_mark):
                try:
                    await lc_mark("skill", resolved["name"], "ACTIVE")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[SKILL] failed to inject skill context: {e}")

    def _skills_index_text(self) -> str:
        """Build the skills index block for system context.

        Returns ``# SKILLS INDEX:`` followed by one ``  /name: description``
        line per registered skill (``  /name`` when no description), or ""
        when no master or no skills are available. Never raises.
        """
        try:
            master = self._skill_master()
            if master is None:
                return ""
            skills = master.list_skills()
            if not skills:
                return ""
            lines = ["# SKILLS INDEX:"]
            for skill in skills:
                name = skill.get("name") or skill.get("id") or "?"
                desc = skill.get("description") or ""
                if desc:
                    lines.append(f"  /{name}: {desc}")
                else:
                    lines.append(f"  /{name}")
            return "\n".join(lines)
        except Exception:
            return ""
