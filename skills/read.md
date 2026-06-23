# Skills

NEXUS AI skill management system. Skills are .md files with YAML frontmatter.

**Version:** 1.0.0

## Structure
- `__init__.py` — `NexusSkillMaster` class (singleton manager)
- `*.md` — Skill files with frontmatter and prompt content

## API
- `NexusSkillMaster(root)` — Initialize
- `list_skills()` — List all skills
- `get_active_prompt()` — Concatenated skill prompts
- `craft_skill(name, prompt)` — Create a skill
- `load_skill(name)` — Load and cache
- `delete_skill(name)` — Remove a skill
