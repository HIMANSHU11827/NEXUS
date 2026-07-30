# Changelog

All notable changes to NEXUS AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
