"""NexusSkillEngine — unified skill discovery, execution, lifecycle, and health.

Merges NexusSkillMaster, V5Skill, and SkillLifecycle into one coherent system.
Supports inject, tool, workflow, and guard execution modes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from skills.experience import SkillExperience

logger = logging.getLogger("NEXUS_SKILL_ENGINE")

#: Env override that restores the legacy "inject every active skill prompt"
#: behavior. When set to "1", runtime selection is bypassed entirely.
NEXUS_ALL_SKILLS_ENV = "NEXUS_ALL_SKILLS_INJECT"

#: Default max number of non-required skills injected per task.
DEFAULT_SELECTION_LIMIT = 3

#: Consecutive failures after which a skill is marked unhealthy and excluded
#: from runtime selection until it succeeds again.
UNHEALTHY_AFTER_CONSECUTIVE_FAILURES = 3

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with",
    "at", "by", "from", "is", "are", "was", "were", "be", "being", "been",
    "use", "using", "i", "you", "it", "this", "that", "please", "help",
    "for", "me", "my", "your", "we", "our", "their", "as", "but", "not",
}


def _tokenize(text: str) -> Set[str]:
    """Split text into a set of lowercase word tokens, dropping stopwords/singles."""
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


@dataclass
class SkillSchema:
    """Validated skill metadata + content."""
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    mode: str = "inject"
    prompt: str = ""
    path: str = ""
    source: str = "legacy"
    requires: List[str] = field(default_factory=list)
    provides: str = ""
    permissions: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    required: bool = False
    timeout_ms: int = 30000
    max_retries: int = 1
    fallback: str = ""
    composable: bool = False
    sandbox_tier: str = "inherit"
    min_nexus_version: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "version": self.version, "category": self.category, "mode": self.mode,
            "prompt": self.prompt, "filepath": self.path, "source": self.source,
            "requires": self.requires, "provides": self.provides,
            "tags": self.tags, "required": self.required,
            "composable": self.composable, "active": True,
        }

    def usage_event(self):
        return {"name": self.name, "skill_id": self.id, "source": self.source, "path": self.path}


@dataclass
class SkillHealth:
    """Per-skill health metrics."""
    skill_id: str
    total_uses: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_timeouts: int = 0
    total_latency_ms: float = 0.0
    last_used: float = 0.0
    last_error: str = ""
    state: str = "unknown"
    consecutive_failures: int = 0
    healthy: bool = True

    @property
    def success_rate(self):
        if self.total_uses == 0:
            return 1.0
        return self.total_successes / self.total_uses

    @property
    def avg_latency_ms(self):
        if self.total_uses == 0:
            return 0.0
        return self.total_latency_ms / self.total_uses

class SkillLifecycleState:
    """Minimal inline lifecycle state machine."""
    VALID_TRANSITIONS = {
        "created": {"active", "error"},
        "active": {"stale", "deleted", "error"},
        "stale": {"active", "archived", "deleted", "error"},
        "archived": {"active", "deleted", "error"},
        "deleted": set(),
        "error": {"active", "deleted"},
    }

    def __init__(self, state_path=None):
        self._states = {}
        self._events = []
        self._state_path = state_path
        if state_path:
            self._load()

    def _load(self):
        if not self._state_path or not os.path.isfile(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._states = data.get("states", {})
            self._events = data.get("events", [])
        except Exception:
            pass

    def _save(self):
        if not self._state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump({"states": self._states, "events": self._events}, f, indent=2)
        except Exception:
            pass

    def register(self, skill_id, initial="created"):
        if skill_id not in self._states:
            self._states[skill_id] = initial
            self._events.append({"id": skill_id, "from": None, "to": initial, "ts": time.time()})
            self._save()

    def get(self, skill_id):
        return self._states.get(skill_id, "unknown")

    def transition(self, skill_id, to_state):
        current = self._states.get(skill_id, "unknown")
        if current == to_state:
            return True
        valid = self.VALID_TRANSITIONS.get(current, set())
        if to_state not in valid:
            return False
        self._states[skill_id] = to_state
        self._events.append({"id": skill_id, "from": current, "to": to_state, "ts": time.time()})
        self._save()
        return True

    def record_use(self, skill_id):
        self.transition(skill_id, "active")
        self._save()

    def stats(self):
        counts = {}
        for s in self._states.values():
            counts[s] = counts.get(s, 0) + 1
        return {"total": len(self._states), "by_state": counts, "events": len(self._events)}

    def get_stale_ids(self, max_days=30):
        now = time.time()
        cutoff = now - (max_days * 86400)
        stale = []
        for e in reversed(self._events):
            if e.get("to") == "active" and e["id"] not in stale:
                if e.get("ts", 0) < cutoff:
                    stale.append(e["id"])
        return stale


class NexusSkillEngine:
    """Unified skill discovery, routing, execution, lifecycle, and health system."""
    _instance = None
    _instances = {}
    #: Directory scanned as the "bundled" skill source. Defaults to this
    #: module's ``skills/`` package dir; overridable (e.g. in tests) to keep
    #: discovery hermetic.
    bundled_dir: Optional[str] = None

    def __new__(cls, root=None):
        resolved = os.path.abspath(root or os.getcwd())
        if resolved not in cls._instances:
            cls._instances[resolved] = super().__new__(cls)
        cls._instance = cls._instances[resolved]
        return cls._instances[resolved]

    def __init__(self, root=None):
        resolved = os.path.abspath(root or os.getcwd())
        if getattr(self, "_initialized_root", "") == resolved:
            return
        self._initialized_root = resolved
        self._root = resolved
        self._skills = {}
        self._event_emitter = None
        self._health = {}
        self._experience = SkillExperience()
        state_path = os.path.join(resolved, "lifecycle", "skill_lifecycle_state.json")
        self._lifecycle = SkillLifecycleState(state_path)
        self._discover_all()
        self._load_health()
        for sid in self._skills:
            self._lifecycle.register(sid, "active")

    def _discover_all(self):
        self._skills.clear()
        canonical = Path(self._root) / ".opencode" / "skills"
        legacy = Path(self._root) / "skills"
        bundled = Path(self.bundled_dir) if self.bundled_dir else Path(os.path.dirname(os.path.abspath(__file__)))
        for base, source in [(canonical, "opencode"), (legacy, "legacy"), (bundled, "bundled")]:
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and (path.name == "SKILL.md" or (path.parent == base and path.suffix.lower() == ".md")):
                    if path.name not in {"README.md", "read.md"}:
                        try:
                            skill = self._parse_skill(path, source)
                            key = skill.id.casefold()
                            if key not in self._skills or source == "opencode":
                                self._skills[key] = skill
                        except Exception as e:
                            logger.debug("Skipping skill: %s", e)

    def _parse_skill(self, path, source):
        content = path.read_text(encoding="utf-8")
        meta = {}
        body = content.strip()
        match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", content, re.DOTALL)
        if match:
            frontmatter_text = match.group(1)
            try:
                import yaml
                fm = yaml.safe_load(frontmatter_text) or {}
                if isinstance(fm, dict):
                    for k, v in fm.items():
                        key = str(k).strip().lower()
                        if key in ("requires", "permissions"):
                            if isinstance(v, list):
                                meta[key] = [str(x).strip() for x in v]
                            elif isinstance(v, str):
                                meta[key] = [x.strip() for x in v.split(",") if x.strip()]
                        elif key in ("timeout_ms", "max_retries"):
                            try:
                                meta[key] = int(v)
                            except (ValueError, TypeError):
                                pass
                        elif key == "composable":
                            meta[key] = str(v).lower() in ("true", "yes", "1")
                        elif key == "created_at":
                            try:
                                meta[key] = float(v)
                            except (ValueError, TypeError):
                                pass
                        else:
                            meta[key] = str(v).strip().strip("\"'")
            except Exception:
                # Fall back to line-by-line parsing
                for line in frontmatter_text.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip().lower()
                        val = value.strip().strip("\"'")
                        if key in ("requires", "permissions"):
                            meta[key] = [v.strip() for v in val.strip("[]").split(",") if v.strip()]
                        elif key in ("timeout_ms", "max_retries"):
                            try:
                                meta[key] = int(val)
                            except ValueError:
                                pass
                        elif key == "composable":
                            meta[key] = val.lower() in ("true", "yes", "1")
                        elif key == "created_at":
                            try:
                                meta[key] = float(val)
                            except ValueError:
                                pass
                        else:
                            meta[key] = val
            body = match.group(2).strip()
        meta["tags"] = self._collect_tags(frontmatter_text if match else "", meta)
        required = str(meta.get("required", "")).strip().lower() in ("true", "yes", "1", "always")
        fallback_id = path.parent.name if path.name == "SKILL.md" else path.stem
        skill_id = str(meta.get("id") or meta.get("name") or fallback_id)
        return SkillSchema(
            id=skill_id,
            name=str(meta.get("name") or skill_id),
            description=str(meta.get("description", "")),
            version=str(meta.get("version", "1.0.0")),
            category=str(meta.get("category", "general")),
            mode=str(meta.get("mode", "inject")),
            prompt=body,
            path=str(path.resolve()),
            source=source,
            requires=list(meta.get("requires", [])),
            provides=str(meta.get("provides", "")),
            permissions=list(meta.get("permissions", [])),
            tags=list(meta.get("tags", [])),
            required=required,
            timeout_ms=int(meta.get("timeout_ms", 30000)),
            max_retries=int(meta.get("max_retries", 1)),
            fallback=str(meta.get("fallback", "")),
            composable=bool(meta.get("composable", False)),
            sandbox_tier=str(meta.get("sandbox_tier", "inherit")),
            min_nexus_version=str(meta.get("min_nexus_version", "")),
            created_at=float(meta.get("created_at", 0.0)),
            updated_at=float(meta.get("updated_at", time.time())),
        )

    # ─── Frontmatter tags ────────────────────────────────────────
    # Tags may appear at the top level (``tags: [...]``), as a comma string
    # (``tags: notes, email``), or nested under ``metadata: {hermes: {tags: [...]}}``
    # (the dominant convention in the bundled skills). Pure stdlib; never raises.

    @staticmethod
    def _collect_tags(frontmatter_text: str, meta: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        try:
            raw = meta.get("tags")
            if isinstance(raw, list):
                tags = [str(t).strip() for t in raw if str(t).strip()]
            elif isinstance(raw, str):
                tags = [t.strip() for t in raw.replace("[", "").replace("]", "").split(",") if t.strip()]
            if tags:
                return tags
            if frontmatter_text:
                try:
                    import yaml
                    fm = yaml.safe_load(frontmatter_text) or {}
                except Exception:
                    fm = None
                if isinstance(fm, dict):
                    nested = fm.get("metadata")
                    if isinstance(nested, dict):
                        for _kv in nested.values():
                            if not isinstance(_kv, dict):
                                continue
                            sub = _kv.get("tags")
                            if isinstance(sub, list):
                                tags.extend(str(t).strip() for t in sub if str(t).strip())
                            elif isinstance(sub, str):
                                tags.extend(t.strip() for t in sub.replace("[", "").replace("]", "").split(",") if t.strip())
                if not tags:
                    # Regex sweep for any ``tags: [a, b]`` style line.
                    for line in frontmatter_text.splitlines():
                        stripped = line.strip()
                        if stripped.lower().startswith("tags:"):
                            raw_tags = stripped.split(":", 1)[1].strip()
                            tags.extend(t.strip() for t in re.findall(r"[A-Za-z0-9_\-]+", raw_tags))
                            if tags:
                                break
        except Exception:
            return []
        seen = set()
        deduped = []
        for t in tags:
            tl = t.casefold()
            if tl not in seen:
                seen.add(tl)
                deduped.append(t)
        return deduped

    def reload(self):
        self._discover_all()
        for sid in self._skills:
            self._lifecycle.register(sid, "active")

    # ─── Query API ────────────────────────────────────────────

    def list_skills(self):
        disabled = self._disabled_skill_ids()
        return [
            {
                "id": s.id, "name": s.name, "description": s.description,
                "version": s.version, "category": s.category, "mode": s.mode,
                "prompt": s.prompt, "filepath": s.path, "source": s.source,
                "requires": s.requires, "composable": s.composable,
                "active": s.id not in disabled and s.name not in disabled,
                "lifecycle_state": self._lifecycle.get(s.id),
                "health": self._health_report_for(s.id),
            }
            for s in self._skills.values()
        ]

    def find_skill(self, name_or_id):
        key = name_or_id.casefold()
        skill = self._skills.get(key)
        if skill:
            return skill.to_dict()
        for s in self._skills.values():
            if s.name.casefold() == key:
                return s.to_dict()
        return None

    def get_skill(self, name_or_id):
        key = name_or_id.casefold()
        skill = self._skills.get(key)
        if skill:
            return skill
        for s in self._skills.values():
            if s.name.casefold() == key:
                return s
        return None

    def get_active_prompt(self, task_text: Optional[str] = None, limit: int = DEFAULT_SELECTION_LIMIT):
        """Build the injected prompt block.

        With a ``task_text`` and no ``NEXUS_ALL_SKILLS_INJECT=1`` override the
        prompt block contains only the runtime-selected skills (top-K matches plus
        any required skills). Without a task the full active-skill prompt
        concatenation is returned for backward compatibility.
        """
        selected = self.select_skills(task_text if task_text else "", limit=limit)
        return "\n\n".join(s.prompt for s in selected if s.prompt)

    # ─── Runtime selection ──────────────────────────────────────

    def select_skills(self, task_text: str = "", limit: int = DEFAULT_SELECTION_LIMIT) -> List["SkillSchema"]:
        """Score active skills against ``task_text`` and return at most ``limit``.

        Matching is a cheap token-overlap on frontmatter ``description`` + ``tags``
        (no dependencies). Skills flagged ``required: true`` are always included
        regardless of score or health. Unhealthy skills (3+ consecutive failures)
        are excluded from scored selection. ``NEXUS_ALL_SKILLS_INJECT=1`` bypasses
        selection entirely. Never raises; on error it falls back to returning every
        active skill so nothing is ever dropped.
        """
        disabled = self._disabled_skill_ids()
        candidates = [
            s
            for s in self._skills.values()
            if s.id not in disabled and s.name not in disabled and s.prompt
        ]
        if os.environ.get(NEXUS_ALL_SKILLS_ENV) == "1":
            return list(candidates)
        if not task_text or not str(task_text).strip():
            return list(candidates)
        try:
            required = [s for s in candidates if getattr(s, "required", False)]
            healthy_pool = [
                s for s in candidates if not getattr(s, "required", False) and self.is_healthy(s.id)
            ]
            scored = [
                (score, s)
                for score, s in ((self._score_skill(s, task_text), s) for s in healthy_pool)
                if score > 0
            ]
            scored.sort(key=lambda pair: (-pair[0], pair[1].name.casefold()))
            top = [s for score, s in scored[: max(0, limit - len(required))]]
            return list(required) + top
        except Exception:
            logger.warning("Skill selection failed; falling back to all skills", exc_info=True)
            return list(candidates)

    @staticmethod
    def _score_skill(skill: "SkillSchema", task_text: str) -> float:
        """Token overlap between the task and the skill's description + tags + name."""
        task_tokens = _tokenize(task_text)
        if not task_tokens:
            return 0.0
        haystack = f"{skill.description} {' '.join(skill.tags)} {skill.name}"
        skill_tokens = _tokenize(haystack)
        if not skill_tokens:
            return 0.0
        matched = len(task_tokens & skill_tokens)
        if matched == 0:
            return 0.0
        # Prefer skills whose vocabulary is densely hit by the task.
        return matched * (matched / len(skill_tokens))

    def is_healthy(self, skill_id: str) -> bool:
        """Untracked skills are considered healthy; unhealthy skills are excluded
        from selection until a successful use resets them."""
        h = self._health.get(skill_id)
        if h is not None:
            return bool(h.healthy)
        return True

    def get_skills_index(self):
        skills = self.list_skills()
        if not skills:
            return ""
        lines = ["# SKILLS INDEX:"]
        for s in skills:
            name = s.get("name", s.get("id", "?"))
            desc = s.get("description", "")
            mode = s.get("mode", "")
            mode_tag = f" [{mode}]" if mode and mode != "inject" else ""
            if desc:
                lines.append(f"  /{name}{mode_tag}: {desc}")
            else:
                lines.append(f"  /{name}{mode_tag}")
        return "\n".join(lines)

    # ─── Routing ───────────────────────────────────────────────

    def route_skill(self, task_description):
        task_lower = task_description.lower()
        best_score = 0.0
        best_skill = None
        for s in self._skills.values():
            score = 0.0
            if s.category.lower() in task_lower:
                score += 3.0
            name_words = set(s.name.lower().replace("-", " ").replace("_", " ").split())
            task_words = set(task_lower.split())
            score += len(name_words & task_words) * 2.0
            desc_words = set(s.description.lower().split())
            score += len(desc_words & task_words) * 0.5
            if score > best_score:
                best_score = score
                best_skill = s
        if best_skill and best_score >= 2.0:
            return best_skill.to_dict()
        return None

    def resolve_dependencies(self, skill_id):
        skill = self.get_skill(skill_id)
        if not skill or not skill.requires:
            return []
        resolved = []
        visited = set()
        def visit(sid):
            if sid in visited:
                return
            visited.add(sid)
            s = self.get_skill(sid)
            if s and s.requires:
                for dep in s.requires:
                    visit(dep)
            resolved.append(sid)
        for dep in skill.requires:
            visit(dep)
        if skill_id not in resolved:
            resolved.append(skill_id)
        return resolved

    def validate_dependencies(self, skill_id):
        skill = self.get_skill(skill_id)
        if not skill:
            return False, f"Skill '{skill_id}' not found"
        if not skill.requires:
            return True, ""
        missing = [r for r in skill.requires if not self.get_skill(r)]
        if missing:
            return False, f"Missing dependencies: {', '.join(missing)}"
        return True, ""

    # ─── Mutation ─────────────────────────────────────────────

    def craft_skill(self, name, prompt, category="crafted", description="", mode="inject"):
        import re as _re
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        safe_name = _re.sub(r"[^a-z0-9_]", "", safe_name)[:64]
        if not safe_name:
            return {"error": "invalid skill name", "created": False}
        fpath = Path(self._root) / ".opencode" / "skills" / safe_name / "SKILL.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        desc = description or f"Auto-crafted skill: {name}"
        content = f"""---
id: {safe_name}
name: {name}
description: {desc}
version: 1.0.0
category: {category}
mode: {mode}
created_at: {time.time()}
---
{prompt}
"""
        fpath.write_text(content, encoding="utf-8")
        self._lifecycle.register(safe_name, "created")
        self._lifecycle.transition(safe_name, "active")
        self._discover_all()
        self._emit("skill.created", {"name": name, "id": safe_name, "path": str(fpath)})
        return {"id": safe_name, "name": name, "filepath": str(fpath), "created": True}

    def delete_skill(self, name_or_id, force=False):
        skill = self.get_skill(name_or_id)
        if not skill:
            return False
        fpath = Path(skill.path)
        crafted_root = (Path(self._root) / ".opencode" / "skills").resolve()
        if fpath.exists():
            if not force:
                try:
                    fpath.resolve().relative_to(crafted_root)
                except ValueError:
                    logger.warning("Refusing to delete non-crafted skill without force: %s", fpath)
                    return False
            import os as _os
            _os.remove(str(fpath))
        key = name_or_id.casefold()
        if key in self._skills:
            del self._skills[key]
        self._lifecycle.transition(skill.id, "deleted")
        self._emit("skill.deleted", {"name": skill.name, "id": skill.id})
        return True

    def update_skill(self, name_or_id, content):
        skill = self.get_skill(name_or_id)
        if not skill:
            return False
        fpath = Path(skill.path)
        fpath.write_text(content, encoding="utf-8")
        self._lifecycle.record_use(skill.id)
        self._discover_all()
        self._emit("skill.updated", {"name": skill.name, "id": skill.id})
        return True

    # ─── Health ───────────────────────────────────────────────

    def _load_health(self):
        path = os.path.join(self._root, "logs", "skill_health.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sid, h in data.items():
                    self._health[sid] = SkillHealth(skill_id=sid, **h)
            except Exception:
                pass

    def _save_health(self):
        path = os.path.join(self._root, "logs", "skill_health.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({sid: {
                    "total_uses": h.total_uses, "total_successes": h.total_successes,
                    "total_failures": h.total_failures, "total_timeouts": h.total_timeouts,
                    "total_latency_ms": h.total_latency_ms, "last_used": h.last_used,
                    "last_error": h.last_error, "state": h.state,
                    "consecutive_failures": h.consecutive_failures, "healthy": h.healthy,
                } for sid, h in self._health.items()}, f, indent=2)
        except Exception:
            pass

    def _health_report_for(self, skill_id):
        h = self._health.get(skill_id)
        if not h:
            return {"uses": 0, "success_rate": 1.0, "avg_latency_ms": 0.0, "healthy": True}
        return {
            "uses": h.total_uses, "successes": h.total_successes,
            "failures": h.total_failures, "timeouts": h.total_timeouts,
            "success_rate": round(h.success_rate, 3),
            "avg_latency_ms": round(h.avg_latency_ms, 1),
            "last_used": h.last_used,
            "consecutive_failures": h.consecutive_failures,
            "healthy": bool(h.healthy),
        }

    def _record_use(self, skill_id, success=True, latency_ms=0.0, error=""):
        """Record a health + experience event. Never raises; a broken skill must
        never take down the engine or the core loop."""
        try:
            h = self._health.get(skill_id)
            if h is None:
                h = SkillHealth(skill_id=skill_id)
                self._health[skill_id] = h
            h.total_uses += 1
            if success:
                h.total_successes += 1
                h.consecutive_failures = 0
                h.healthy = True
            else:
                h.total_failures += 1
                h.consecutive_failures += 1
                if h.consecutive_failures >= UNHEALTHY_AFTER_CONSECUTIVE_FAILURES:
                    h.healthy = False
                    h.state = "unhealthy"
            h.total_latency_ms += latency_ms
            h.last_used = time.time()
            if error:
                h.last_error = str(error)[:500]
            h.state = self._lifecycle.get(skill_id) if not (h.consecutive_failures >= UNHEALTHY_AFTER_CONSECUTIVE_FAILURES) else "unhealthy"
            self._lifecycle.record_use(skill_id)
            self._experience.record(skill_id, success=success, latency_ms=latency_ms)
            self._save_health()
        except Exception:
            logger.warning("record_use failed for skill %r", skill_id, exc_info=True)

    def record_use(self, skill_id, success=True, latency_ms=0.0, error=""):
        """Public alias for :meth:`_record_use` (never raises)."""
        self._record_use(skill_id, success=success, latency_ms=latency_ms, error=error)

    def get_experience(self, skill_id: Optional[str] = None):
        """Per-skill experience data for the ledger / feedback tooling.

        Returns the dict stored in ``~/.nexus/skills/experience.json`` for one
        skill (or everything when ``skill_id`` is None). Never raises.
        """
        try:
            return self._experience.get(skill_id)
        except Exception:
            return {}

    def health_report(self):
        total = len(self._skills)
        active = sum(1 for h in self._health.values() if h.total_uses > 0)
        overall = 0
        if active > 0:
            overall = sum(h.success_rate for h in self._health.values() if h.total_uses > 0) / active
        return {
            "total_skills": total,
            "active_skills": active,
            "overall_success_rate": round(overall, 3),
            "lifecycle": self._lifecycle.stats(),
            "per_skill": {sid: self._health_report_for(sid) for sid in self._skills},
            "stale_skills": self._lifecycle.get_stale_ids(),
        }

    # ─── Events ───────────────────────────────────────────────

    def set_event_emitter(self, emitter):
        self._event_emitter = emitter

    def _emit(self, event_type, payload):
        if self._event_emitter:
            try:
                self._event_emitter({
                    "event_type": event_type,
                    "kind": "skill",
                    "timestamp": time.time(),
                    "payload": payload,
                })
            except Exception:
                pass

    # ─── Config ────────────────────────────────────────────────

    def _disabled_skill_ids(self):
        config_path = Path(self._root) / "configure" / "settings.yml"
        if not config_path.exists():
            return set()
        try:
            import yaml
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return set()
        if not isinstance(loaded, dict):
            return set()
        skills_cfg = loaded.get("skills", {})
        disabled = skills_cfg.get("disabled_skills", [])
        if isinstance(disabled, dict):
            result = {str(n) for n, v in disabled.items() if v}
        elif isinstance(disabled, list):
            result = {str(n) for n in disabled}
        else:
            result = set()
        custom = skills_cfg.get("custom_skill_configs", {})
        if isinstance(custom, dict):
            for name, meta in custom.items():
                if isinstance(meta, dict) and meta.get("active") is False:
                    result.add(str(name))
        return {i for i in result if i}

    # ─── Debug ────────────────────────────────────────────────

    def deep_scan(self):
        return json.dumps(self.list_skills(), indent=2)

    def __repr__(self):
        return f"<NexusSkillEngine skills={len(self._skills)} root={self._root}>"


def get_skill_engine(root=None):
    """Get or create the singleton NexusSkillEngine."""
    return NexusSkillEngine(root)
