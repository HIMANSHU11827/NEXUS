# Agent Framework Research Matrix — Nexus AI

> **Superseded for architecture decisions on 2026-07-18.** This historical
> matrix contains stale implementation counts and claims from an older NEXUS
> state. Use [HARNESS_LANDSCAPE_2026-07.md](HARNESS_LANDSCAPE_2026-07.md) for the
> current, source-backed comparison and prioritized harness gaps.

> Research conducted for Nexus AI architecture decisions.
> Based on documentation review, source code analysis, and public references.

## Coding Agents

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 1 | **OpenCode** | Docs/Repo | Agent framework with build/plan/explore/scout/general agents; skill system with SKILL.md; AGENTS.md for durable instructions; .opencode/commands for repeatable tasks | SKILL.md format, AGENTS.md pattern, agent delegation model, command system | Tight coupling to specific LLM provider | Use .opencode/ project structure for Nexus development | .opencode/skills/, AGENTS.md, .opencode/commands/ | High |
| 2 | **Claude Code** | Docs/Repo | Terminal-first agent with read/write/edit/glob/grep tools; SSE event streaming; permission system; MCP support | Tool permission model, event streaming, file edit with diff | Cloud-only dependency | Already designed; Nexus has local-first providers | tools/, sandbox/, server/ | High |
| 3 | **OpenAI Agents SDK** | Docs/Repo | Agent loop with handoffs, guardrails, structured outputs; async execution; function tools | Handoff protocol between agents, structured output schemas | Over-engineered for local use | Can inform subagent orchestration | orchestrators/loop.py, orchestrators/architect.py | Medium |
| 4 | **GitHub Copilot Agent** | Docs/Repo | VS Code integration, context-aware code suggestions, workspace understanding | Workspace context loading, code intelligence | Cloud dependency, limited customizability | Inform workspace panel design | gui/src/components/workspace/ | Medium |
| 5 | **OpenHands** | Repo | Browser-based agent UI with terminal, editor, file browser; event stream architecture | Event-driven architecture, sandboxed execution | Heavy Docker dependency | Compare event streaming design | server/, tools/, sandbox/ | Medium |
| 6 | **SWE-agent** | Repo | Specialized for SWE-bench; agent-computer interface (ACI); focused tool design | Tool interface design, command formatting | Too academic/narrow for general use | Inform command execution tool | tools/nexus_tools/registry.py, sandbox/ | Low |
| 7 | **Aider** | Repo | Map-refine architecture with repository map; edit format; benchmark leader | Repo map for code understanding, diff-based editing | Focus on edit format only | Inform file editing workflows | tools/reading/, tools/creating/, tools/modifying/, tools/deleting/, nexus/events.py (file diff events) | Medium |
| 8 | **Cursor** | Docs/Repo | IDE-integrated agent with @-mentions, Composer, multi-file editing | @-mention context, multi-file edit coordination | IDE lock-in | Inform workspace panel and file operations | gui/src/components/workspace/ | Medium |
| 9 | **Manus** | Article | Browser-based agent workspace with timeline, sandbox, computer use | Timeline UI for agent actions, right-side computer panel | Closed source, limited info | Reference for workspace panel design | gui/src/components/workspace/ | Low |
| 10 | **Lemon AI** | Repo | Timeline-based agent UI with computer use, tool calls, file edits | Timeline bubbles for tool/command/file events | Focus on demo/UI only | Reference for GUI timeline | gui/src/App.tsx (WorkActivityTimeline), components/Workspace/ | Low |

## Agent Frameworks

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 11 | **LangGraph** | Docs/Repo | Graph-based agent state machines; checkpointing; streaming | Durable checkpoints and streaming lifecycle ideas | Complexity for simple tasks | Current loop is unified streaming/tool runtime, not the removed SCAState enum | orchestrators/loop.py | Medium |
| 12 | **Semantic Kernel** | Docs/Repo | Planners (sequential/stepwise); function calling; memory; plugins | Plugin architecture, stepwise planner | Microsoft ecosystem dependency | Inform plugin system and planning | plugins/, orchestrators/ | Medium |
| 13 | **AutoGen** | Repo | Multi-agent conversations; group chat; agent roles | Multi-agent conversation patterns, role-based agents | Complex agent communication | Inform subagent orchestration | orchestrators/, providers/ | Medium |
| 14 | **CrewAI** | Repo | Role-based agent teams; sequential/hierarchical processes; tool integration | Role-based agent orchestration, sequential/hierarchical process | Over-abstraction for simple cases | Inform Hive/multi-agent system | orchestrators/mission_control.py, hive/ | Medium |
| 15 | **Pydantic AI** | Docs/Repo | Type-safe agent framework with Pydantic models; structured results | Type-safe event models, validation with dataclasses | Python 3.14+ compatibility | CanonicalEvent uses frozen dataclass | nexus/events.py (CanonicalEvent) | High |
| 16 | **LlamaIndex Agents** | Repo | RAG + agent workflows; query engine tools; data connectors | RAG integration, query engine pattern | Focus on data/indexing | Inform RAG/knowledge tools | rag/, memory/, tools/knowledge/ | Medium |
| 17 | **Haystack Agents** | Repo | Pipeline-based agent architecture; tool integration | Pipeline architecture for tool chains | Focus on search/RAG | Inform tool chain execution | tools/, orchestrators/ | Low |
| 18 | **SmolAgents** | Repo | Minimal agent implementation; code agent; tool calling | Minimal agent design, code-as-action pattern | Limited feature set | Simplify smaller agent loops | orchestrators/loop.py | Low |
| 19 | **DSPy** | Repo | Programming-not-prompting; optimizer-driven prompts; LM modules | Prompt optimization, modular LM programming | Academic research overhead | Inform prompt building | prompts/, providers/ | Low |

## Tool Protocols

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 20 | **MCP** | Docs/Repo | Standardized tool/resource/prompt protocol; stdio/SSE transport; JSON-RPC | MCP transport layer, tool discovery, resource model | Lock-in to specific protocol | Already implemented in mcp/ | mcp/server.py, mcp/client/ | High |
| 21 | **OpenAI Tool Schema** | Docs | Function calling schema; structured tool definitions | Tool schema with JSON Schema params | OpenAI-specific format | Inform .jsnol metadata format | tools/nexus_tools/registry.py (ToolEntry) | High |
| 22 | **JSON-RPC** | Spec | Lightweight RPC protocol; request/response/notification | MCP transport layer | No built-in streaming | MCP uses JSON-RPC | mcp/server.py | High |

## Streaming Systems

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 23 | **SSE (Server-Sent Events)** | Spec | Unidirectional event streaming from server to client; auto-reconnect | Main streaming mechanism, event framing with data:/event: lines | Bidirectional communication needs | Already used in server/ | server/__init__.py (SSE streaming) | High |
| 24 | **WebSocket** | Spec | Bidirectional real-time communication | Low-latency event streaming, command/control | Complexity for simple use cases | Consider for future GUI | server/ | Medium |
| 25 | **Event Sourcing** | Pattern | Append-only event log; state reconstruction from events | Event store for run history, replay | Eventual consistency complexity | Event log in memory/logs | nexus/events.py, memory/ | Medium |

## GUI Agent Workspaces

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 26 | **VS Code Agent Panels** | Docs | Agent workspace with terminal, editor, search, problems | Multi-panel workspace layout | IDE lock-in | Reference for panel layout | gui/src/components/workspace/ | High |
| 27 | **OpenHands UI** | Repo | Browser-based agent workspace with file explorer, terminal, chat | Integrated agent workspace in browser | Heavy React dependencies | Already has React GUI | gui/src/App.tsx | Medium |

## TUI

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 28 | **Rich** | Repo | Terminal formatting; live display; tables; panels; syntax highlighting | Legacy shell rendering and diagnostics | Overhead for simple output | Used in legacy shell/ | shell/__init__.py | Medium |
| 29 | **Textual** | Repo | Full terminal application framework; widgets; CSS styling | If rebuilding a future terminal UI, Textual provides better UX | Learning curve | Consider only for a future TUI v2 | shell/ | Low |
| 30 | **Ink** | Repo | React for TUI; component-based; Yoga layout | TUI rendering | React dependency in TUI | Already used in tui/ | tui/nexus-tui.tsx | Medium |

## Planning Systems

| # | Project | Type | What it does well | Copy for Nexus | Avoid | Impact | Related Nexus files | Confidence |
|---|---------|------|-------------------|----------------|-------|--------|---------------------|------------|
| 31 | **Simple Plan** | Pattern | Numbered task list; status tracking; step-by-step execution | Simple plan mode (understand → inspect → edit → test) | No flexibility for complex tasks | Already in nexus/events.py (plan.* events) | orchestrators/loop.py, nexus/events.py | High |
| 32 | **Phase Plan** | Pattern | Multi-phase execution with sub-goals; phase status tracking | Advanced plan mode with phases and sub-goals | Over-engineering for simple tasks | Already in event model | orchestrators/loop.py, nexus/events.py | High |

---

**Total references: 32** (limited by current research scope; expand when internet access is available)

## Key Architecture Decisions for Nexus AI

1. **Event model**: Use `CanonicalEvent` frozen dataclass (from Pydantic AI), ~50 event types, all lifecycles covered
2. **Streaming**: SSE from FastAPI server (inspired by Claude Code, MCP)
3. **Tool system**: Registry with `.jsnol` metadata + async execution (inspired by OpenCode, OpenAI tool schema)
4. **Agent loop**: Unified streaming/tool runtime with permission, risk, sandbox, verification, memory persistence, and canonical work events
5. **Security**: 3-tier sandbox + deterministic risk scorer (inspired by Claude Code's permission model)
6. **MCP**: Stdio JSON-RPC server (based on official MCP spec)
7. **Plugins**: Dynamic import-based with lifecycle hooks
8. **Multi-agent**: HiveEngine + skill system (inspired by CrewAI, AutoGen)
9. **GUI**: React workspace with timeline, file explorer, terminal, canvas panels (inspired by Manus, OpenHands)
10. **TUI**: Ink-based API client by default; Rich shell remains a legacy direct interface
