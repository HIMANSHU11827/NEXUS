# Evolution

NEXUS AI self-evolution system — forges, learning, improvement, auto-version tracking.

**Version:** 2.0.0

## Forges (Auto-Creation & Refinement)
- `tool_forge/` — ToolForge: auto-create and refine tools with version bump
- `skill_forge/` — SkillForge + SkillSynthesizer: auto-create skills
- `plugin_forge/` — PluginForge: auto-create plugins
- `memory_forge/` — MemoryForge: create and refine memory entries
- `knowledge_forge/` — KnowledgeForge: create knowledge entries
- `log_forge/` — LogAnalyzer: pattern analysis

## Core Modules
- `logs/` — EvolutionLog: consolidated logging
- `status/` — EvolutionStatus: system health reporting
- `ledger/` — EvolutionLedger: immutable record keeping
- `nudge/` — NudgeEngine: behavioral nudges
- `intent/` — NexusIntentEngine: intent evolution
- `self_improvement/` — SelfImprovementEngine: session analysis & improvement
- `sop/` — Standard Operating Procedures
- `version/` — VersionManager: auto-version tracking for all 39 modules (all scripts have `__version__` inline)

## Auto-Version System
Every forge auto-bumps versions on refine (minor default, major on upgrade).
All 39 `.jsnol` files tracked with version metadata. All `scripts/*.py` have inline `__version__`.
