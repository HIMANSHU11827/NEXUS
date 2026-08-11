# Workspace Path Validation

Validate bash-command paths are within the current workspace.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/workspace_path_validation.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
NEXUS should validate that paths provided in bash commands are within the current workspace, not just rely on the sandbox to block them. This prevents user confusion and provides clearer feedback by validating up front.

## Notes
Part of the path-validation family: overlaps with `sandbox_path_validation`, `sandbox_path_validator`, and `workspace_path_guard`; the sandbox itself already blocks out-of-workspace commands.
