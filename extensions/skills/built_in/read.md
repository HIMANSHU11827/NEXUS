# Skills

NEXUS AI skill management system — SKILL.md files with YAML frontmatter, discovery, crafting, routing, and lifecycle.

**Version:** 2.0.0

## Structure
- `__init__.py` — `NexusSkillMaster` (root-keyed singleton manager)
- `engine.py` — `NexusSkillEngine`: unified discovery, routing, execution, lifecycle, and health
- `registry.py` — `SkillRegistry` with `SkillRecord` dataclass and side-effect-free discovery
- `experience.py` — `SkillExperience` per-skill usage tracking at `~/.nexus/skills/experience.json`
- `*/SKILL.md` — Skill files with frontmatter (id, name, description, version, prompt, tags, requires, mode, …)

## Master API (`NexusSkillMaster`)
- `list_skills()` — All discovered skills with active state from config
- `get_active_prompt(task_text)` — Concatenated prompts for runtime-selected active skills only
- `select_skills(task_text)` — Token-overlap scoring (description + tags); `required: true` always included; `NEXUS_ALL_SKILLS_INJECT=1` bypasses selection
- `craft_skill(name, prompt)` — Create skill in `.opencode/skills/`
- `load_skill(name)` — Reload and check cache
- `delete_skill(name, force)` — Remove with safety checks (non-crafted files need `force`)
- `deep_scan()` — JSON dump of all skills
- `find_skill(id_or_name)` — Lookup by id or name

## Engine (`NexusSkillEngine`)
- `route_skill(task_description)` — Score-based routing to the best skill
- `resolve_dependencies(skill_id)` — DFS dependency resolution; `validate_dependencies()` reports missing deps
- `craft_skill` / `delete_skill` / `update_skill` — mutations emitting `skill.created` / `skill.deleted` / `skill.updated` events
- `SkillLifecycleState` — state machine (`created → active → stale → archived → deleted`, plus `error`), persisted to `lifecycle/skill_lifecycle_state.json`
- `SkillHealth` — per-skill metrics (uses, success rate, latency, consecutive failures) persisted at `logs/skill_health.json`; skills with 3+ consecutive failures are marked unhealthy and excluded from selection
- `get_active_prompt()` — same runtime selection as the master, plus health gating
- `SkillSchema` — validated metadata (id, name, description, version, category, mode, requires, provides, permissions, tags, required, timeout_ms, sandbox_tier, …)

## Registry (`SkillRegistry`)
- Canonical `.opencode/skills/<name>/SKILL.md` always wins over legacy `skills/<name>/SKILL.md` / `skills/<name>.md` on id collision

## Installed Skills
69 SKILL.md files across 14 categories (vendored Hermes Agent skill set): apple, autonomous-ai-agents, creative, email, github, index-cache, media, mlops, note-taking, productivity, research, smart-home, social-media, software-development.
