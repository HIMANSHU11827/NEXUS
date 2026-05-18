# Agent Context Files

NEXUS can generate compact repository instruction files for coding agents:

- `AGENTS.md` for agents that support the shared agent-instructions convention.
- `CLAUDE.md` for Claude Code-style project memory.

The generator uses the local code graph at `workspace/code_graph.json` and falls back to building the graph when no graph exists. This keeps the context grounded in real repository structure instead of hand-written guesses.

## Commands

Preview:

```powershell
python -c "from core.code_intelligence.agent_context import AgentContextGenerator; print(AgentContextGenerator('.').generate('AGENTS.md'))"
```

Write both files:

```powershell
python -c "from core.code_intelligence.agent_context import AgentContextGenerator; print([r.to_dict() for r in AgentContextGenerator('.').write(force=True)])"
```

Through the NEXUS tool registry:

```python
registry.execute("agent_context", command="preview", target="AGENTS.md")
registry.execute("agent_context", command="write", targets=["AGENTS.md", "CLAUDE.md"], force=True)
```

## Why It Exists

Modern coding-agent workflows benefit from a predictable, concise repository briefing: architecture, verification commands, tool boundaries, generated-file exclusions, and safety posture. NEXUS keeps that briefing refreshed from its own structural graph so external agents can start with useful context and fewer wasteful discovery passes.
