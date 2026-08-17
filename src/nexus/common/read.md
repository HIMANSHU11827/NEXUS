# Utilities

Shared utility functions, helper modules, and common libraries used across the NEXUS platform.

**Version:** 2.0.0

## Modules (18)

### Logging & Sanitization
- `logger.py` — `NexusLogger`: structured logging with component routing
- `context_scrubber.py` — `StreamingContextScrubber`, `MessageSanitizer`: scrub/clean context before send
- `output_cleaner.py` — `clean_model_output()`: normalize raw model output

### Security & Guarding
- `encryption.py` — `NexusEncryption`: encryption utilities
- `runtime_guard.py` — `assert_not_rewriting_core`, `guarded_open` / `guarded_write_text` / `guarded_append_text` / `guarded_jsonl_append`, `verify_core_integrity`, `CoreRewriteBlocked`
- `sandbox.py` — `NexusSandbox`: isolated execution helper

### Data & Math
- `compression.py` — `CompressionTool`: data compression
- `math_ops.py` — `NexusMath`: math helpers
- `token_counter.py` — `TokenCounter`: token counting

### Discovery, Singleton & Paths
- `discovery.py` — `NexusAutoDiscover`: component discovery
- `singleton.py` — `ThreadSafeSingleton` base + `singleton` decorator
- `nexus_path.py` — NEXUS home/profiles path resolution (`get_nexus_home`, `get_active_profile`, …)
- `nexus_compat.py` — compat shims (`import_requests`, `s`, `safe_round`, `itail`, `safe_del`, `sx`)

### Session & Engine Plumbing
- `session_bus.py` — active-session tracking (`get_active_session_id`, `set_active_session_id`, `sync_loop_from_disk`)
- `engine_compiler.py` — `compile_llama_cpp()`: llama.cpp build
- `engine_manager.py` — `get_engine_status()`, `load_or_create_config()`, `reload_engine()`: engine lifecycle management
- `speed_test.py` — `test_remote_speed()`: remote speed diagnostics

### General
- `helpers.py` — `NexusHelpers`: miscellaneous shared helpers
