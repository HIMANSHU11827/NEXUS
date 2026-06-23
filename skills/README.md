# NEXUS AI Skills Module

Skills are `.md` files stored in the `skills/` directory with YAML frontmatter:

```yaml
---
id: skill-name
name: Skill Name
description: What this skill does
category: tool
---
Skill prompt content here...
```

## Usage

```python
from skills import NexusSkillMaster

# Initialize (singleton)
master = NexusSkillMaster("/path/to/project")

# List all loaded skills
skills = master.list_skills()

# Get concatenated active prompt
prompt = master.get_active_prompt()

# Create a new skill
result = master.craft_skill("My Skill", "You are an expert at...")

# Reload skills from disk
master.load_skill("my_skill")

# Delete a skill
master.delete_skill("my_skill")

# Full deep scan
scan = master.deep_scan()
```
