# Unified NEXUS Graph

NEXUS has several specialized stores:

- `workspace/code_graph.json`
- `workspace/memory_graph.json`
- `workspace/evidence_ledger.json`
- `workspace/mission_replay.jsonl`
- `workspace/tool_economy.json`
- `workspace/benchmark_history.jsonl`
- `workspace/failure_vaccines.jsonl`
- `workspace/self_improvement.json`
- `workspace/todos.json`
- `logs/sessions/*.json`
- `logs/swarm/*`, including swarm contracts, handoffs, and checkpoints
- `AGENTS.md` and `CLAUDE.md`

The unified graph keeps those source stores intact and builds one queryable index at:

```text
workspace/unified_graph.json
```

## Tool Commands

Build or refresh:

```python
registry.execute("unified_graph", command="build")
```

Summarize:

```python
registry.execute("unified_graph", command="summary")
```

Search across code, memory, evidence, sessions, tools, and benchmarks:

```python
registry.execute("unified_graph", command="search", query="diagnostics")
```

Inspect a local neighborhood:

```python
registry.execute("unified_graph", command="neighborhood", node_id="mission:default", depth=2)
```

Close a mission/session into the graph:

```python
registry.execute("unified_graph", command="close_session", mission_id="default", note="final verification complete")
```

## Design

The unified graph is an index, not a replacement database. Each original system remains the authority for its own data. The unified graph connects them so agents can answer questions such as:

- Which code structures, tools, tests, and evidence were involved in a mission?
- What failures or memories are linked to a tool or workflow?
- What did the system recently verify, and which commands proved it?
- Which runtime events relate to a benchmark, evidence claim, or memory?

This keeps NEXUS from scattering intelligence across many disconnected files while preserving simple, inspectable source formats.
