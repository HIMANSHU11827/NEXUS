# NEXUS Kernel

Singleton runtime (`NexusKernel`) — thread-safe lazy-loaded central hub for all subsystems.

**Version:** 2.0.0

## Structure
- `__init__.py` — `NexusKernel` class (thread-safe singleton, 340 lines)
- 19 lazy-loaded properties: config, moe, moa, nerve, omni, hyper, researcher, persistence, hal, horizons, local_brain, trainer, indexer, intent, prover, tools, telemetry, rag, hive, plugins

## Core Responsibilities
- MoE Router: dynamic model tiering with auto-detection, fallback chains, profile switching
- NATE: 5-layer fused tool calling runtime (adaptive schema, universal adapter, execution graph, self-healing)
- Tool discovery and sandboxed execution via ToolRegistry
- Session lifecycle, workspace ownership, state persistence
- Stats, health tracking, and evolution integration
- All subsystems fail gracefully with ImportError fallback