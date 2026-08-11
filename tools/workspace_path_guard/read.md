# Workspace Path Guard

Enforce and log workspace-escape violations.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/workspace_path_guard.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
The sandbox currently blocks paths outside the workspace, but no explicit guard or validation exists to prevent workspace-escape attempts. This tool would enforce and log such violations so escape attempts are visible and actionable rather than silently blocked.

## Notes
Part of the path-validation family: overlaps with `sandbox_path_validation`, `sandbox_path_validator`, and `workspace_path_validation`; adds explicit enforcement/logging on top of the sandbox's existing blocking.
