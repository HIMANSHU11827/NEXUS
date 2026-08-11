# Sandbox Path Validation

Validate/expand workspace-only sandbox paths with actionable fallback.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/sandbox_path_validation.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
NEXUS lacks a tool to validate/expand workspace-only sandbox paths, allowing external paths like `C:\Users\himan\Desktop\NEXUS` to be rejected without an actionable fallback. This tool would validate and expand paths against the workspace sandbox, suggesting a corrected alternative when a path is outside it.

## Notes
Part of the path-validation family: overlaps with `sandbox_path_validator`, `workspace_path_validation`, and `workspace_path_guard`; the sandbox itself already blocks out-of-workspace commands.
