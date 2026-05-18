---
name: NEXUS-agent
description: Complete guide to using and extending NEXUS Agent — CLI usage, setup, configuration, spawning additional agents, gateway platforms, skills, voice, tools, profiles, and a concise contributor reference. Load this skill when helping users configure NEXUS, troubleshoot issues, spawn agent instances, or make code contributions.
version: 2.0.0
author: NEXUS Agent + Teknium
license: MIT
metadata:
  NEXUS:
    tags: [NEXUS, setup, configuration, multi-agent, spawning, cli, gateway, development]
    homepage: https://github.com/NousResearch/NEXUS-agent
    related_skills: [claude-code, codex, opencode]
---

# NEXUS Agent

NEXUS Agent is an open-source AI agent framework by Nous Research that runs in your terminal, messaging platforms, and IDEs. It belongs to the same category as Claude Code (Anthropic), Codex (OpenAI), and OpenClaw — autonomous coding and task-execution agents that use tool calling to interact with your system. NEXUS works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, local models, and 15+ others) and runs on Linux, macOS, and WSL.

What makes NEXUS different:

- **Self-improving through skills** — NEXUS learns from experience by saving reusable procedures as skills. When it solves a complex problem, discovers a workflow, or gets corrected, it can persist that knowledge as a skill document that loads into future sessions. Skills accumulate over time, making the agent better at your specific tasks and environment.
- **Persistent memory across sessions** — remembers who you are, your preferences, environment details, and lessons learned. Pluggable memory backends (built-in, Honcho, Mem0, and more) let you choose how memory works.
- **Multi-platform gateway** — the same agent runs on Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Email, and 8+ other platforms with full tool access, not just chat.
- **Provider-agnostic** — swap models and providers mid-workflow without changing anything else. Credential pools rotate across multiple API keys automatically.
- **Profiles** — run multiple independent NEXUS instances with isolated configs, sessions, skills, and memory.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem.

People use NEXUS for software development, research, system administration, data analysis, content creation, home automation, and anything else that benefits from an AI agent with persistent context and full system access.

**This skill helps you work with NEXUS Agent effectively** — setting it up, configuring features, spawning additional agent instances, troubleshooting issues, finding the right commands and settings, and understanding how the system works when you need to extend or contribute to it.

**Docs:** https://NEXUS-agent.nousresearch.com/docs/

## Quick Start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/NousResearch/NEXUS-agent/main/scripts/install.sh | bash

# Interactive chat (default)
NEXUS

# Single query
NEXUS chat -q "What is the capital of France?"

# Setup wizard
NEXUS setup

# Change model/provider
NEXUS model

# Check health
NEXUS doctor
```

---

## CLI Reference

### Global Flags

```
NEXUS [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

No subcommand defaults to `chat`.

### Chat

```
NEXUS chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
NEXUS setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
NEXUS model                Interactive model/provider picker
NEXUS config               View current config
NEXUS config edit          Open config.yaml in $EDITOR
NEXUS config set KEY VAL   Set a config value
NEXUS config path          Print config.yaml path
NEXUS config env-path      Print .env path
NEXUS config check         Check for missing/outdated config
NEXUS config migrate       Update config with new options
NEXUS login [--provider P] OAuth login (nous, openai-codex)
NEXUS logout               Clear stored auth
NEXUS doctor [--fix]       Check dependencies and config
NEXUS status [--all]       Show component status
```

### Tools & Skills

```
NEXUS tools                Interactive tool enable/disable (curses UI)
NEXUS tools list           Show all tools and status
NEXUS tools enable NAME    Enable a toolset
NEXUS tools disable NAME   Disable a toolset

NEXUS skills list          List installed skills
NEXUS skills search QUERY  Search the skills hub
NEXUS skills install ID    Install a skill
NEXUS skills inspect ID    Preview without installing
NEXUS skills config        Enable/disable skills per platform
NEXUS skills check         Check for updates
NEXUS skills update        Update outdated skills
NEXUS skills uninstall N   Remove a hub skill
NEXUS skills publish PATH  Publish to registry
NEXUS skills browse        Browse all available skills
NEXUS skills tap add REPO  Add a GitHub repo as skill source
```

### MCP Servers

```
NEXUS mcp serve            Run NEXUS as an MCP server
NEXUS mcp add NAME         Add an MCP server (--url or --command)
NEXUS mcp remove NAME      Remove an MCP server
NEXUS mcp list             List configured servers
NEXUS mcp test NAME        Test connection
NEXUS mcp configure NAME   Toggle tool selection
```

### Gateway (Messaging Platforms)

```
NEXUS gateway run          Start gateway foreground
NEXUS gateway install      Install as background service
NEXUS gateway start/stop   Control the service
NEXUS gateway restart      Restart the service
NEXUS gateway status       Check status
NEXUS gateway setup        Configure platforms
```

Supported platforms: Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Matrix, Mattermost, Home Assistant, DingTalk, Feishu, WeCom, API Server, Webhooks, Open WebUI.

Platform docs: https://NEXUS-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
NEXUS sessions list        List recent sessions
NEXUS sessions browse      Interactive picker
NEXUS sessions export OUT  Export to JSONL
NEXUS sessions rename ID T Rename a session
NEXUS sessions delete ID   Delete a session
NEXUS sessions prune       Clean up old sessions (--older-than N days)
NEXUS sessions stats       Session store statistics
```

### Cron Jobs

```
NEXUS cron list            List jobs (--all for disabled)
NEXUS cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
NEXUS cron edit ID         Edit schedule, prompt, delivery
NEXUS cron pause/resume ID Control job state
NEXUS cron run ID          Trigger on next tick
NEXUS cron remove ID       Delete a job
NEXUS cron status          Scheduler status
```

### Webhooks

```
NEXUS webhook subscribe N  Create route at /webhooks/<name>
NEXUS webhook list         List subscriptions
NEXUS webhook remove NAME  Remove a subscription
NEXUS webhook test NAME    Send a test POST
```

### Profiles

```
NEXUS profile list         List all profiles
NEXUS profile create NAME  Create (--clone, --clone-all, --clone-from)
NEXUS profile use NAME     Set sticky default
NEXUS profile delete NAME  Delete a profile
NEXUS profile show NAME    Show details
NEXUS profile alias NAME   Manage wrapper scripts
NEXUS profile rename A B   Rename a profile
NEXUS profile export NAME  Export to tar.gz
NEXUS profile import FILE  Import from archive
```

### Credential Pools

```
NEXUS auth add             Interactive credential wizard
NEXUS auth list [PROVIDER] List pooled credentials
NEXUS auth remove P INDEX  Remove by provider + index
NEXUS auth reset PROVIDER  Clear exhaustion status
```

### Other

```
NEXUS insights [--days N]  Usage analytics
NEXUS update               Update to latest version
NEXUS pairing list/approve/revoke  DM authorization
NEXUS plugins list/install/remove  Plugin management
NEXUS honcho setup/status  Honcho memory integration
NEXUS memory setup/status/off  Memory provider config
NEXUS completion bash|zsh  Shell completions
NEXUS acp                  ACP server (IDE integration)
NEXUS claw migrate         Migrate from OpenClaw
NEXUS uninstall            Uninstall NEXUS
```

---

## Slash Commands (In-Session)

Type these during an interactive chat session.

### Session Control
```
/new (/reset)        Fresh session
/clear               Clear screen + new session (CLI)
/retry               Resend last message
/undo                Remove last exchange
/title [name]        Name the session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/resume [name]       Resume a named session
```

### Configuration
```
/config              Show config (CLI)
/model [name]        Show or change model
/provider            Show provider info
/prompt [text]       View/set system prompt (CLI)
/personality [name]  Set personality
/reasoning [level]   Set reasoning (none|low|medium|high|xhigh|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### Tools & Skills
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/cron                Manage cron jobs (CLI)
/reload-mcp          Reload MCP servers
/plugins             List plugins (CLI)
```

### Info
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/status              Session info (gateway)
/profile             Active profile info
```

### Exit
```
/quit (/exit, /q)    Exit CLI
```

---

## Key Paths & Config

```
~/.NEXUS/config.yaml       Main configuration
~/.NEXUS/.env              API keys and secrets
~/.NEXUS/skills/           Installed skills
~/.NEXUS/sessions/         Session transcripts
~/.NEXUS/logs/             Gateway and error logs
~/.NEXUS/auth.json         OAuth tokens and credential pools
~/.NEXUS/NEXUS-agent/     Source code (if git-installed)
```

Profiles use `~/.NEXUS/profiles/<name>/` with the same layout.

### Config Sections

Edit with `NEXUS config edit` or `NEXUS config set section.key value`.

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh/modal), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `tool_progress`, `show_reasoning`, `show_cost` |
| `stt` | `enabled`, `provider` (local/groq/openai) |
| `tts` | `provider` (edge/elevenlabs/openai/kokoro/fish) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `max_iterations` (50) |
| `smart_model_routing` | `enabled`, `cheap_model` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |

Full config reference: https://NEXUS-agent.nousresearch.com/docs/user-guide/configuration

### Providers

18 providers supported. Set via `NEXUS model` or `NEXUS setup`.

| Provider | Auth | Key env var |
|----------|------|-------------|
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Nous Portal | OAuth | `NEXUS login --provider nous` |
| OpenAI Codex | OAuth | `NEXUS login --provider openai-codex` |
| GitHub Copilot | Token | `COPILOT_GITHUB_TOKEN` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| Hugging Face | Token | `HF_TOKEN` |
| Z.AI / GLM | API key | `GLM_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| Kimi / Moonshot | API key | `KIMI_API_KEY` |
| Alibaba / DashScope | API key | `DASHSCOPE_API_KEY` |
| Kilo Code | API key | `KILOCODE_API_KEY` |
| Custom endpoint | Config | `model.base_url` + `model.api_key` in config.yaml |

Plus: AI Gateway, OpenCode Zen, OpenCode Go, MiniMax CN, GitHub Copilot ACP.

Full provider docs: https://NEXUS-agent.nousresearch.com/docs/integrations/providers

### Toolsets

Enable/disable via `NEXUS tools` (interactive) or `NEXUS tools enable/disable NAME`.

| Toolset | What it provides |
|---------|-----------------|
| `web` | Web search and content extraction |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `vision` | Image analysis |
| `image_gen` | AI image generation |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `moa` | Mixture of Agents (off by default) |
| `homeassistant` | Smart home control (off by default) |

Tool changes take effect on `/reset` (new session). They do NOT apply mid-conversation to preserve prompt caching.

---

## Voice & Transcription

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

Provider priority (auto-detected):
1. **Local faster-whisper** — free, no API key: `pip install faster-whisper`
2. **Groq Whisper** — free tier: set `GROQ_API_KEY`
3. **OpenAI Whisper** — paid: set `VOICE_TOOLS_OPENAI_KEY`

Config:
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| Kokoro (local) | None | Free |
| Fish Audio | `FISH_AUDIO_API_KEY` | Free tier |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

---

## Spawning Additional NEXUS Instances

Run additional NEXUS processes as fully independent subprocesses — separate sessions, tools, and environments.

### When to Use This vs delegate_task

| | `delegate_task` | Spawning `NEXUS` process |
|-|-----------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-Shot Mode

```
terminal(command="NEXUS chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# Background for long tasks:
terminal(command="NEXUS chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### Interactive PTY Mode (via tmux)

NEXUS uses prompt_toolkit, which requires a real terminal. Use tmux for interactive spawning:

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'NEXUS'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-Agent Coordination

```
# Agent A: backend
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'NEXUS -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B: frontend
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'NEXUS -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### Session Resume

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'NEXUS --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'NEXUS --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Tips

- **Prefer `delegate_task` for quick subtasks** — less overhead than spawning a full process
- **Use `-w` (worktree mode)** when spawning agents that edit code — prevents git conflicts
- **Set timeouts** for one-shot mode — complex tasks can take 5-10 minutes
- **Use `NEXUS chat -q` for fire-and-forget** — no PTY needed
- **Use tmux for interactive sessions** — raw PTY mode has `\r` vs `\n` issues with prompt_toolkit
- **For scheduled tasks**, use the `cronjob` tool instead of spawning — handles delivery and retry

---

## Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. Restart gateway: `/restart`

### Tool not available
1. `NEXUS tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `NEXUS doctor` — check config and dependencies
2. `NEXUS login` — re-authenticate OAuth providers
3. Check `.env` has the right API key

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** `/restart` reloads gateway config
- **Code changes:** Restart the CLI or gateway process

### Skills not showing
1. `NEXUS skills list` — verify installed
2. `NEXUS skills config` — check platform enablement
3. Load explicitly: `/skill name` or `NEXUS -s name`

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.NEXUS/logs/gateway.log | tail -20
```

---

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Config options | `NEXUS config edit` or [Configuration docs](https://NEXUS-agent.nousresearch.com/docs/user-guide/configuration) |
| Available tools | `NEXUS tools list` or [Tools reference](https://NEXUS-agent.nousresearch.com/docs/reference/tools-reference) |
| Slash commands | `/help` in session or [Slash commands reference](https://NEXUS-agent.nousresearch.com/docs/reference/slash-commands) |
| Skills catalog | `NEXUS skills browse` or [Skills catalog](https://NEXUS-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `NEXUS model` or [Providers guide](https://NEXUS-agent.nousresearch.com/docs/integrations/providers) |
| Platform setup | `NEXUS gateway setup` or [Messaging docs](https://NEXUS-agent.nousresearch.com/docs/user-guide/messaging/) |
| MCP servers | `NEXUS mcp list` or [MCP guide](https://NEXUS-agent.nousresearch.com/docs/user-guide/features/mcp) |
| Profiles | `NEXUS profile list` or [Profiles docs](https://NEXUS-agent.nousresearch.com/docs/user-guide/profiles) |
| Cron jobs | `NEXUS cron list` or [Cron docs](https://NEXUS-agent.nousresearch.com/docs/user-guide/features/cron) |
| Memory | `NEXUS memory status` or [Memory docs](https://NEXUS-agent.nousresearch.com/docs/user-guide/features/memory) |
| Env variables | `NEXUS config env-path` or [Env vars reference](https://NEXUS-agent.nousresearch.com/docs/reference/environment-variables) |
| CLI commands | `NEXUS --help` or [CLI reference](https://NEXUS-agent.nousresearch.com/docs/reference/cli-commands) |
| Gateway logs | `~/.NEXUS/logs/gateway.log` |
| Session files | `~/.NEXUS/sessions/` or `NEXUS sessions browse` |
| Source code | `~/.NEXUS/NEXUS-agent/` |

---

## Contributor Quick Reference

For occasional contributors and PR authors. Full developer docs: https://NEXUS-agent.nousresearch.com/docs/developer-guide/

### Project Layout

```
NEXUS-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (NEXUSCLI)
├── NEXUS_state.py       # SQLite session store
├── agent/                # Prompt builder, compression, display, adapters
├── NEXUS_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # ~3000 pytest tests
└── website/              # Docusaurus docs site
```

Config: `~/.NEXUS/config.yaml` (settings), `~/.NEXUS/.env` (API keys).

### Adding a Tool (3 files)

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add import** in `model_tools.py` → `_discover_tools()` list.

**3. Add to `toolsets.py`** → `_NEXUS_CORE_TOOLS` list.

All handlers must return JSON strings. Use `get_NEXUS_home()` for paths, never hardcode `~/.NEXUS`.

### Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `NEXUS_cli/commands.py`
2. Add handler in `cli.py` → `process_command()`
3. (Optional) Add gateway handler in `gateway/run.py`

All consumers (help text, autocomplete, Telegram menu, Slack mapping) derive from the central registry automatically.

### Agent Loop (High Level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### Testing

```bash
source venv/bin/activate  # or .venv/bin/activate
python -m pytest tests/ -o 'addopts=' -q   # Full suite
python -m pytest tests/tools/ -q            # Specific area
```

- Tests auto-redirect `NEXUS_HOME` to temp dirs — never touch real `~/.NEXUS/`
- Run full suite before pushing any change
- Use `-o 'addopts='` to clear any baked-in pytest flags

### Commit Conventions

```
type: concise subject line

Optional body.
```

Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`

### Key Rules

- **Never break prompt caching** — don't change context, tools, or system prompt mid-conversation
- **Message role alternation** — never two assistant or two user messages in a row
- Use `get_NEXUS_home()` from `NEXUS_constants` for all paths (profile-safe)
- Config values go in `config.yaml`, secrets go in `.env`
- New tools need a `check_fn` so they only appear when requirements are met
