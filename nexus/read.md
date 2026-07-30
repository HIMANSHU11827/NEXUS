# Nexus (Boot Loader)

Primary entry point — boot sequence, process lifecycle, command aliases, and runtime launch.

**Version:** 2.0.0

## Entry
```powershell
python -m nexus             # TUI (default)
python -m nexus --gui       # React GUI + backend
python -m nexus --server    # FastAPI server on :8000
python -m nexus --gateway   # Multi-platform gateway
python -m nexus --setup     # Setup wizard
python -m nexus --quick     # Quick start with defaults
python -m nexus --reset     # Factory reset
python -m nexus --shell     # Legacy compatibility shell
```

## Components
- `__init__.py` — `boot()` function (687 lines)
- Boot sequence: env setup → alias resolution → arg parse → mode dispatch
- Command aliases: nexus-tui, nexus-gui, nexus-server, nexus-gateway, nexus-setup, etc.
- First-run wizard with interactive menu (msvcrt-based keyboard navigation)
- Export/import system (config + full system with ZIP)
- `events.py` — `CanonicalEvent` dataclass + `EVENT_TYPES` (50 event types) + `infer_event_type()` heuristic
- `commands.py` — `CommandRegistry` singleton with 30+ built-in slash commands
- `runtime.py` — `ChatRunRequest`, session/turn ID sanitization, provider normalization
- `run_context.py` — `RunContext` durable identity + `start_run_context()` / `list_run_contexts()`
