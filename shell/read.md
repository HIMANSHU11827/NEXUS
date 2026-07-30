# Shell (Legacy)

Legacy Rich-based shell — compatibility shim for `python -m nexus --shell`.

**Version:** 2.0.0

## Status
Legacy — the Ink TUI is the primary interface. This module is kept for backwards compatibility.

## Components
- `__init__.py` — `NexusShell` class (127 lines): `_run_bash()`, `_handle_slash()`, `_render_event()`, `_stream_response()`
- `TaskTracker` — Simple in-memory task registry
