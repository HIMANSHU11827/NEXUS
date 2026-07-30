# Skills

NEXUS AI skill management system — SKILL.md files with YAML frontmatter, discovery, crafting, and lifecycle.

**Version:** 2.0.0

## Structure
- `__init__.py` — `NexusSkillMaster` class (root-keyed singleton manager)
- `registry.py` — `SkillRegistry` with `SkillRecord` dataclass and discovery
- `*.md` — Skill files with frontmatter (id, name, description, version, prompt)

## API
- `list_skills()` — All discovered skills with active state from config
- `get_active_prompt()` — Concatenated prompts for active skills only
- `craft_skill(name, prompt)` — Create skill in `.opencode/skills/`
- `load_skill(name)` — Load and cache
- `delete_skill(name)` — Remove with safety checks
- `deep_scan()` — JSON dump of all skills
- `find_skill(id_or_name)` — Lookup by id or name

## Installed Skills
- tool-error-handling, test-skill, web-search-parameter-validation, environment-detection, web-search-error-handling, tool-error-resolution
