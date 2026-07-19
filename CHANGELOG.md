# Changelog

All notable changes to NEXUS AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
