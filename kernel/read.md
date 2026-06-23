# NEXUS Kernel

Singleton runtime (`NexusKernel`) — lazy-loads config, providers, tools, RAG, memory, and telemetry.

**Version:** 1.0.0

## Structure
- `__init__.py` — `NexusKernel` class (thread-safe singleton)
- Properties: `config`, `providers`, `tools`, `rag`, `memory`, `telemetry`

## Core Responsibilities
- MoE Router: dynamic model tiering (NANO to EXTREME)
- Provider registry and capability-aware fallback
- Tool discovery and sandboxed execution
- Session lifecycle and workspace ownership
- Stats and boot health tracking