# Changelog

All notable changes to NEXUS AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-08-05

### Added
- Gateway expanded to 21 platform adapters (BlueBubbles, DingTalk, Discord, Email, Feishu, Google Chat, IRC, LINE, Matrix, Mattermost, Meta, QQBot, Signal, Slack, SMS, Teams, Telegram, WeCom, Weixin, WhatsApp, Yuanbao) with webhook server, HMAC fail-closed verification, and supervised lifecycle (`GatewaySupervisor`)
- V5 direct model/tool loop completed — tool-call extraction, permission policies (PAORR), planning gates, work items, background runner (see `LOOP_RESEARCH_REPORT.md`)
- Evolution subsystems rebuilt from stubs: `researcher`, `omni_kernel`, `ensemble`, `hyper_kernel` — now functional and tested
- `tools/reasoning` upgraded to v3.0.0 — real LLM-backed HyperReasoningEngine (planner + critic + verifier, uncertainty estimation)
- `tools/system` — `disk` and `process` actions implemented
- `tools/planning` rebuilt — single truthful `todo.md` plan with stable task IDs and work-item sync
- TUI v3.0 "activity-rich" redesign — activity cards, hive panel, command palette, status bar, 133 slash commands

### Changed
- Kernel now registers 20 lazy-loaded subsystems (was 19)
- Skills tree updated to vendored Hermes Agent skill set — 69 SKILL.md files across 14 categories
- Docs overhaul: all `read.md` files updated to match current code (tools, mcp, tui, gui, utils, memory, skills, hive, prompts, kernel, nexus, bin, voice)
- All tool docs corrected to reflect actual behavior (`task`, `knowledge`, `code_search`, `modifying`, `git_ops`, `web_search`, `terminal`)
- 13 unimplemented tool stubs documented honestly as `unavailable` (e.g. `live_news_tool`, `workspace_path_guard`)

### Fixed
- `mcp/tool/read.md` — incorrect `tool.call(...)` example replaced with `await tool.execute(...)`
- `tests/read.md` — broken code fence and wrong directory references fixed
- `tests/core/core.md` — rewritten to describe the actual tests
- Tool docs no longer advertise nonexistent features (`knowledge delete`, `code_search struct`, `task blocked` status)

## [2.0.0] - 2026-07-30

### Added
- New GUI: React 18 + Vite + TypeScript frontend rebuilt from scratch (25 source files, ~5000 lines)
- New agent loop: `NexusLoop` rebuilt (3555 lines) with 8 tool call extraction strategies, stable and reliable
- Evolution system upgraded: 6 forges (tool, skill, plugin, memory, knowledge, log) + VersionManager tracking 39 modules
- NATE 5-layer fused tool engine: adaptive schema, universal adapter, execution graph, self-healing
- HyperReasoningEngine: deterministic planner/critic/verifier with uncertainty scoring
- OAuth 2.0 / PKCE / Device Code: 9 provider implementations (Codex, Claude, Copilot, Gemini, Grok, OpenRouter, Qwen, MiniMax, Chutes)
- Voice pipeline: 4 STT backends (faster-whisper, transformers, whisper.cpp, llama-cpp) + KittenTTS
- Multi-platform gateway: 10 platform adapters (Discord, Telegram, WhatsApp, Meta, Slack, Signal, Matrix, Mattermost, Email, SMS)
- Plugin system: PluginManager with lifecycle hooks, trust model, and tool registration
- Authentication: OAuth 2.0 (Google, GitHub) + token auth + gateway authorization
- MCP integration: NEXUSMCPServer + MCPClient + MCPTool adapter (full stdio protocol)
- Memory: Multi-source MemoryManager with parallel prefetch (session + RAG + failures + knowledge)

### Changed
- All read.md files updated to v2.0.0+ with accurate descriptions
- AGENTS.md, README.md, NEXUS_CODEBASE_MAP.md fully rewritten to reflect current state
- ROADMAP_STATUS.md updated (67.9% weighted completion)
- `orchestrators/architect.py` and `mission_control.py` removed — planning uses `todo.md` + `planning` tool
- Cleaned up 9 orphaned `.pyc` files and 3 orphaned tool directories (find, glob, read)
- Removed stale test session artifacts from server/logs/

### Fixed
- `SPECIAL_FOCUS.md` updated — all 8 repair areas now marked as completed
- `AGENT_CONTEXT.md` updated — references `_ground_context()` instead of deleted `core.code_intelligence`
- All internal markdown links verified and working (0 broken links in docs/)

## [1.0.0] - 2026-06-25

### Added
- Upload latest NEXUS source code and voice system updates
- Improve loop: add tool descriptions in grounding, build proper system prompt with available tools
- DeepSeek V4 Flash config, fix loop deprecation, TASK_COMPLETE in stream errors
- Update all read.md directory descriptions A-to-Z with version info and structure
- Add version info to all 37 module/tool/test markdown files
- Update docs: fix broken paths, reflect evolution restructure and auto-version system

### Fixed
- Fix tool system: add BaseTool, wire ToolRegistry to instantiate tool classes, all 10 tools now executable
- Fix critical runtime blockers: add nexus_compat, session_bus, assets, intelligence stubs, fix kernel intent path, create missing packages

## [0.9.0] - 2026-06-23

### Added
- Embed `__version__` in all tool/evolution scripts, add version to config YAMLs
- Add version system: VersionManager + version fields in all 39 .jsnol files
- Add read.md documentation to all folders
- Add read.md documentation for all core folders

### Changed
- Rebuild NEXUS core: evolution, skills, config, tools structure

### Restructured
- Rename forge → tool_forge, log_analyzer → log_forge, add logs/ module
- Merge skill_synthesizer → skill_forge, create logs/, backward compat kept
- Restructure evolution modules into per-folder format with jsnol+scripts+md
- Restructure tests into per-folder format with jsnol+scripts+md

### Fixed
- Update log_forge naming, fix evolution read.md

### Removed
- Reset demo version bump

## [0.8.0] - 2026-06-13

### Changed
- Refactor codebase: flatten core folder, rename modules to packages, align tool naming to `_tool.py`, delete browser automation, and update documentation

## [0.1.0] - 2026-05-18

### Added
- Initial commit of NEXUS AI
