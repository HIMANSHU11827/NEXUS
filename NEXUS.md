# NEXUS AI

## What NEXUS is

NEXUS AI is an **AI agent framework and runtime** — an autonomous, multi-agent
system that can understand a codebase, plan and execute tasks, call tools
directly, repair failures, remember project history, and operate through a
terminal-first workflow or a visual GUI. It is local-first but **not local-only**:
it is provider-agnostic and can run on local models, cloud APIs, or
authenticated (OAuth) providers — exactly like OpenCode or Hermes Agent.

NEXUS is not a chatbot with plugins. It is an operator-grade AI development
and orchestration system: a unified agent loop, multi-model routing, durable
memory, autonomous multi-agent workflows, and a control surface for long-running
work.

## Core identity (one line)

> NEXUS is a local-first, provider-agnostic **multi-agent AI runtime** with a
> built-in **Hive** agent system (parallel / sequential / specialist / sub /
> team agents) and a 3-tier model provider stack (local / API / auth-based).

## Hive — the multi-agent system

NEXUS ships a first-class multi-agent orchestration engine in `hive/`. A Hive
run spawns autonomous agents that run as isolated LLM calls with persona-tailored
prompts, emit `subagent.*` work events through the same pipeline as the main
agent (GUI, TUI, SSE, persistence), and persist every run/team/agent/task to a
SQLite store so a crash can be recovered and resumed.

Hive supports these agent types (see `NexusHiveEngine.spawn_hive` ->
`agent_categories` and `HiveCapability`):

| Agent type | What it does | Code surface |
|------------|--------------|-------------|
| **Parallel agents** | Many independent agents run concurrently (a "hive"), bounded by `NEXUS_HIVE_MAX_CONCURRENCY` (default 8) | `engine.spawn_hive`, `engine.spawn_agent` |
| **Sequential agents** | Agents run in a staged plan (sequential + parallel groups), each stage gated on the previous | `capability.py` staged execution (§18) |
| **Specialist agents** | Role/specialization-tailored agents pulled from the specialization registry (coding, research, security, testing, devops, …) | `specializations.py`, `get_specialization` |
| **Sub-agents** | Single isolated LLM sub-agent with a dedicated persona; emits `subagent.*` events | `SubAgent` in `engine.py` |
| **Team agents** | A reusable group of Hive agents (`AgentTeamSpec`) working toward one shared goal, built by `TeamBuilder` from `required_specializations` | `teams.py`, `TeamBuilder` |

Hive also provides: capability inheritance (role-based), a scoped handoff
blackboard, checkpoints, result merging/consolidation, quorum/critic/verifier
patterns, dead-agent replacement, and per-agent resource budgets.

## Model providers — local, API, and auth-based (not local-only)

NEXUS is **provider-agnostic**. The provider stack lives in
`models/providers/` and is organized in three tiers:

| Tier | Directory | Examples |
|------|-----------|----------|
| **Local** | `models/providers/local/` | Ollama, LM Studio (incl. auto), llama.cpp, sandbox interpreter — fully offline, no API key |
| **API (key-based)** | `models/providers/api/` | OpenAI, Anthropic, Google Gemini, DeepSeek, Groq, Mistral, Cohere, Azure OpenAI, OpenRouter, Perplexity, Qwen, xAI, Together, Replicate, SambaNova, Fireworks, NVIDIA, HuggingFace, Zupra, and more (20+ vendors) |
| **Auth / OAuth (login-based)** | `models/providers/auth/` + `auth/oauth/` | Claude (Anthropic), Codex (OpenAI), GitHub Copilot, Gemini, Grok, OpenRouter, Qwen, MiniMax, Chutes, and the OpenCode CLI provider — via OAuth device-code / PKCE flows |

So NEXUS supports *all* model providers the same way OpenCode, Hermes Agent,
and other top coding agents do: you can run a local Llama 3 model, a cloud
GPT/Claude/Gemini, or log in with your existing AI subscription. It is not
restricted to local-only operation.

## Interfaces

A mission can be sent from any of these surfaces; all are internally connected
via one `session_id` and shared history:

| Interface | Start | Path |
|-----------|-------|------|
| TUI (Ink client) | `python -m nexus` | `apps/tui/` + API backend on `:8000` |
| GUI | `python -m nexus --gui` | React app + API backend |
| Server API | `python -m nexus --server` | standalone FastAPI app on `:8000` |
| Gateway | `python -m nexus --gateway` | `gateways/` — Telegram, Discord, WhatsApp, Slack, Signal, Matrix, SMS (Twilio) + more |

## Quick Start

```powershell
uv sync                  # creates .venv + installs the nexus package
nexus                    # TUI
nexus --gui              # GUI
nexus --server           # API on :8000
nexus --gateway          # messaging gateway
nexus --setup            # setup wizard (providers + gateways incl. SMS)
```

Provider keys / OAuth logins are configured in `configure/provider.yml` and
environment variables. Local providers (Ollama, LM Studio, llama.cpp) need no
key. See `configure/provider.yml` for all configured providers.

## More

See [`README.md`](../README.md) for the full architecture and
[`docs/README.md`](docs/README.md) for the documentation index, roadmap, and
engineering directives.
