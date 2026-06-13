# Agent Context Files

NEXUS generates a compact repository instruction file for coding agents:

- `NEXUS.md` — project memory and structural briefing for agents and humans.

The generator uses the local code graph at `workspace/code_graph.json` and falls back to building the graph when no graph exists. This keeps the context grounded in real repository structure instead of hand-written guesses.

## Commands

Preview:

```powershell
python -c "from core.code_intelligence.agent_context import AgentContextGenerator; print(AgentContextGenerator('.').generate('NEXUS.md'))"
```

Write:

```powershell
python -c "from core.code_intelligence.agent_context import AgentContextGenerator; print([r.to_dict() for r in AgentContextGenerator('.').write(force=True)])"
```

Through the NEXUS tool registry:

```python
registry.execute("agent_context", command="preview", target="NEXUS.md")
registry.execute("agent_context", command="write", targets=["NEXUS.md"], force=True)
```

## Why It Exists

Modern coding-agent workflows benefit from a predictable, concise repository briefing: architecture, verification commands, tool boundaries, generated-file exclusions, and safety posture. NEXUS keeps that briefing refreshed from its own structural graph so external agents can start with useful context and fewer wasteful discovery passes.
