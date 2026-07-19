# Skills

NEXUS AI skill management system. Skills are .md files with YAML frontmatter.

**Version:** 1.0.0

## Structure
- `__init__.py` — `NexusSkillMaster` class (root-keyed manager)
- `*.md` — Skill files with frontmatter and prompt content

## API
- `NexusSkillMaster(root)` — Initialize a manager for one resolved project root
- `list_skills()` — List all discovered skills, including `active` state from `config/nexus_config.yaml`
- `get_active_prompt()` — Concatenated prompts for active skills only; disabled skills stay discoverable but do not enter model context
- `craft_skill(name, prompt)` — Create a skill
- `load_skill(name)` — Load and cache
- `delete_skill(name)` — Remove a crafted `.opencode/skills` skill
- `delete_skill(name, force=True)` — Remove a non-crafted legacy/project skill when the caller has explicit ownership
