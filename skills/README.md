# Nexus local skills

This directory is the self-contained skill source used by Nexus discovery.
Hermes Agent's public skill tree is vendored here as local prompt and workflow
knowledge; Nexus does not import Hermes at runtime or fetch skills from the
network. Discovery walks nested directories and loads only `SKILL.md` records.

The previous Nexus-only skills are preserved in
`workspace/legacy-skills-backup-20260804` so the migration is reversible.

Skills describe capabilities and workflows. They do not grant permissions by
themselves: execution still goes through Nexus's registered tools, sandbox,
safety checks, and MCP trust boundaries.
