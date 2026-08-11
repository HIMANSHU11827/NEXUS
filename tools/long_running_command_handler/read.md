# Long Running Command Handler

Async/background task support or checkpointing for commands exceeding 300s.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/long_running_command_handler.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
The Bash tool times out on commands exceeding 300 seconds. This tool would provide async/background task support or checkpointing so long-running commands can continue without blocking the main loop, and results can be collected once finished.

## Notes
Overlaps with `bash_timeout_control` (shorter timeouts / background runs) and the `terminal` tool's fixed timeout; no existing tool currently offers background task management.
