# Prompts

NexusPromptEngine — token-efficient dynamic prompt builder for the sovereign cognitive loop.

**Version:** 2.0.0

## Components
- `__init__.py` — `NexusPromptEngine`: `build_super_prompt()`, `build_live_system_prompt()`, segment builders
- Dynamic protocol injection (Self-Correction/Improvement protocols)
- Identity, adaptive collaboration, tools, rules, and special focus assembly

## Segment Builders
- `get_role_segment(role)` — role-specific segment: ARCHITECT / DEBUGGER / SECURITY / HIVE
- `get_adaptive_collaboration_segment(intent, complexity, needs_tools)` — single-coworker posture (companion / worker / engineer / researcher / operator / strategist)
- `get_environment_segment(root_dir, context_map)` — OS, root, hardware footprint (kernel HAL), grounding map
- `get_tool_segment(intent_hints)` — live tool list from `ToolRegistry` (JSON-only tool format)
- `get_rules_segment(root_dir)` — all project rules from `nexus.json`
- `get_special_focus_segment(root_dir)` — durable audit/repair directives from `docs/SPECIAL_FOCUS.md`

## Prompt Builders
- `build_live_system_prompt(...)` — compact, token-budgeted (`max_chars`, default 4000) prompt using only light segments; never raises
- `build_super_prompt(...)` — full prompt with KnowledgeVault experiential recall + kernel horizons
- `build_tool_prompt()` — ultra-compact tool-only prompt
- `build_local_prompt()` — compact prompt for small local chat models
