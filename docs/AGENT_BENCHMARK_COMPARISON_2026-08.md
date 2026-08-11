# Nexus Agent Benchmark and Reference Comparison

Date: 2026-08-09

## Scope

This report separates framework reliability from model capability. Nexus is
benchmarked locally without external providers. Hermes Agent and Agent Zero
were downloaded into `references/hermes-agent` and `references/agent-zero` and
inspected as architecture references; they were not scored as competitors
because their provider, container, and desktop dependencies are different.

## Benchmark layers

| Layer | What it measures | Nexus status |
|---|---|---|
| Framework contract | Replay verdicts, malformed action handling, canonical events, safety precedence | 3/3 pass |
| End-to-end runtime | Real provider request, SSE, timeout, resume, tool evidence | Exercise separately per provider/configuration |
| Coding capability | Patch correctness on repository tasks | Use a fixed SWE-bench-style local subset, not a synthetic pass rate |
| General assistant capability | Tool use, browsing, file reasoning, multi-step completion | Use a small GAIA-inspired internal set until licensed/public data is configured |
| Long-horizon reliability | Restart recovery, leases, duplicate side-effect prevention, bounded memory | Partial; requires a dedicated soak harness |

## Reference patterns worth adopting

### Hermes Agent

Source inspection showed mature operational patterns in:

- `tools/async_delegation.py`: bounded concurrent background delegation,
  durable lifecycle records, parent-session binding, and shutdown cleanup.
- `tools/checkpoint_manager.py` and `agent/context_compressor.py`: explicit
  checkpoint/context boundaries instead of unbounded transcript growth.
- `tools/tool_output_limits.py`, `tools/skill_provenance.py`, and
  `tools/skills_guard.py`: bounded tool output plus provenance and skill safety.
- `batch_runner.py` and `trajectory_compressor.py`: normalized trajectories,
  tool statistics, and training/evaluation-ready artifacts.

### Agent Zero

Source inspection showed a different but complementary emphasis:

- `tools/call_subordinate.py` and agent profiles: explicit role-based
  delegation with project-aware subordinate selection.
- project instructions and memory paths: project isolation for instructions,
  secrets, memories, repositories, and model presets.
- Dockerized runtime and browser/desktop surfaces: strong environment
  isolation and visible intervention for high-impact actions.
- scheduler and scheduled-task skills: durable scheduled work as a first-class
  capability rather than an undocumented loop.

## Nexus changes in this cycle

- Added `benchmarks/nexus_agent_benchmark.py`, a provider-independent suite.
- Added `tests/test_nexus_agent_benchmark.py`.
- Fixed safety rule precedence so credential reads and command chains are not
  classified as safe reads.
- Stored the generated report at
  `workspace/benchmark_history/nexus-agent-framework-v1.json`.

## Important non-goals

Passing the local framework benchmark does not mean Nexus matches Hermes,
Agent Zero, SWE-bench, or GAIA. Those are different evaluation targets. A
credible next phase needs the same model, task set, tool permissions, timeout,
workspace, and verification rules across every compared framework.
