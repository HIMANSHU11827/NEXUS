# Merged structure notes

The project now exposes a simpler merged layout:

- cognition/ re-exports reasoning, intelligence, and telemetry helpers.
- core/ provides a unified runtime namespace for shared services.
- shared/ gathers reusable helper utilities and compatibility exports.
- knowledge_memory_context/ is the merged package for memory, context, and knowledge.
- memory/, context/, and knowledge/ are also present as top-level folders for compatibility.
- kernel/telemetry.py offers a compatibility shim for telemetry access.

This keeps imports working while making the high-level organization easier to follow.
