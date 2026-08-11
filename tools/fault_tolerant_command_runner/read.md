# Fault Tolerant Command Runner

Exit code 3221225794 (0xC0000409) crash handling / crash-dump capture / safer retry flags.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/fault_tolerant_command_runner.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
Exit code 3221225794 (0xC0000409) indicates a stack buffer overrun or software crash that standard command execution does not handle. This tool would capture OS-level crash dumps and retry failed commands with safer execution flags so that crashes are diagnosed instead of surfaced as opaque errors.

## Notes
Overlaps with the `terminal` tool's subprocess execution; would augment it with crash handling and retry logic.
