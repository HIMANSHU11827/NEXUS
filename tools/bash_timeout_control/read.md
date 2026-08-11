# Bash Timeout Control

Bash tool has no timeout parameter or async execution option; need shorter timeouts / background runs.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/bash_timeout_control.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
Long-running commands currently fail because the Bash tool has no timeout parameter or async execution option. This tool would let NEXUS set shorter timeouts per invocation or run commands in the background so they do not block the main loop.

## Notes
Overlaps with `long_running_command_handler` (async/background execution for commands exceeding 300s) and the `terminal` tool's fixed subprocess timeout.
