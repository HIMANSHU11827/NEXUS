# Skill Curator

**Version:** 2.0.0

Background skill lifecycle manager for NEXUS AI. Runs during idle periods to auto-archive stale skills, manage pin states, and consolidate duplicates.

## Features
- Auto-archive: skills not used in N days go to `skills/.archive/<name>/`
- Pin system: `pinned: true` in frontmatter exempts from auto-transitions
- Usage tracking: `workspace/skill_usage.json` logs use_count, last_activity_at, state
- Stale detection: configurable threshold (default 30 days)
- Never deletes — only archives to recoverable `.archive/` directory
