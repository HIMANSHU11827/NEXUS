# NEXUS CLI Commands Reference

The CLI (`cli/nexus-cli.tsx`) is an Ink-based TypeScript thin client that talks to the FastAPI backend on port 8000. This document catalogs every command with its current behavior.

## Command Categories

### Core Chat & Session
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/chat` | — | Sends message to kernel (default when no `/` prefix) |
| `/new` | — | Creates new conversation via `POST /api/sessions/new` |
| `/resume` | `/load` | Loads conversation via `POST /api/sessions/load` |
| `/rename` | — | Renames session via `POST /api/sessions/rename` |
| `/delete-session` | — | Deletes session via `DELETE /api/sessions/{id}` |
| `/conversations` | `/sessions` | Lists sessions via `GET /api/sessions` |
| `/history` | — | Reloads current session history via `GET /api/history` |
| `/commands` | `/help`, `/` | Shows full command list |
| `/exit` | `/quit` | Exits the CLI process |
| `/clear` | — | Clears visible chat history (local only) |
| `/compact` | — | Trims visible history to N messages (local only, default 12) |
| `/stop` | — | Stops working state locally |
| `/btw` | — | Logs a side note locally |

### Provider & Model Management
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/provider` | `/connect` | Shows/sets provider. `list` opens sidebar panel. `open <id>` shows detail. `add <name>` creates new. `model <id> <name>` sets model. `endpoint <id> <url>` sets endpoint. `enable/disable <id>` toggles. |
| `/providers` | — | Opens provider list in sidebar panel (clickable rows) |
| `/model` | `/models` | Shows/sets model. `list` shows all. `set <provider> <model>` configures. |
| `/mode` | `/permissions` | Shows provider + model + permission mode. `auto\|plan\|accept` sets permission mode. |
| `/logout` | — | Clears provider override |
| `/login` | — | Shows API key status |

### Tool, Skill & Plugin Management
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/tools` | `/tool` | Lists tools from registry via `GET /api/tools` |
| `/skills` | `/skill` | Lists skills via `GET /api/skills` |
| `/plugins` | `/plugin` | Lists plugins via `GET /api/plugins`. `enable/disable/remove <id>` manages. |
| `/mcp` | `/mcps`, `/mpc` | Lists MCP servers. `enable/disable <id>` toggles. `reload` reconnects. |
| `/enable` | `/on` | Enables tool/skill/mcp/plugin/provider/feature by name |
| `/disable` | `/off` | Disables tool/skill/mcp/plugin/provider/feature by name |
| `/reload` | `/reload-plugins`, `/reload-skills` | Reloads session/tasks/plugins/skills/tools/mcp/providers/nexus |

### File & Directory
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/ls` | — | Lists directory contents |
| `/tree` | — | Shows directory tree (2 levels) |
| `/cat` | — | Previews a file |
| `/pwd` | — | Shows project root path |
| `/where` | — | Shows project, cwd, session, api, gui paths |
| `/cd` | — | Changes CLI working directory |
| `/add-dir` | — | Adds extra working directory to kernel |
| `/files` | — | Searches workspace files via `GET /api/files?q=` |
| `/readme` | — | Previews README.md |
| `/docs` | — | Lists docs/ directory |
| `/init` | — | Creates `docs/NEXUS.md` if missing |
| `/memory` | — | Shows or opens memory file |
| `/paste` | — | Attaches clipboard image |

### Git & Review
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/git` | `/gst`, `/gstatus` | Shows git status/diff/log/branch |
| `/diff` | — | Shows `git diff --stat` |
| `/branch` | — | Shows current git branch |
| `/log` | — | Shows `git log --oneline -12` |
| `/review` | — | Shows git diff for code review |
| `/code-review` | — | Alias for /review |
| `/security-review` | — | Shows git diff for security review |
| `/simplify` | — | Shows git diff for simplification review |
| `/ultrareview` | — | Alias for /code-review |
| `/rewind` | — | Shows recent commits + working tree state |

### Voice
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/voice` | `/voi`, `/mic`, `/talk` | Starts/stops voice mode. `on`/`auto` starts daemon. `manual` starts PTT mode. `text` starts text fallback. `off` stops. Status shown in sidebar and equalizer meter. |

Uses `.venv\Scripts\python.exe` when available (Windows fix). stderr output captured even for non-JSON errors.

### Engine & Training
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/engine` | `/eng`, `/backend` | Manages local AI engine. `status` shows state. `compile` builds llama.cpp. `set <key> <val>` updates params. `reload [model]` hot-reloads. `train [steps]` starts fine-tuning. |

### System & Status
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/status` | — | Shows full system status via `GET /api/status` |
| `/health` | — | Shows API + runtime health |
| `/debug` | — | Shows debug diagnostics |
| `/doctor` | — | Runs health checks (API, git, CLI typecheck, Python compile) |
| `/features` | — | Lists runtime feature flags |
| `/config` | `/settings` | Shows/sets config sections via `GET/POST /api/manage` |
| `/env` | — | Shows safe env summary |
| `/version` | — | Shows node/npm/python/git versions |
| `/usage` | `/cost`, `/stats` | Shows token usage stats |
| `/context` | — | Shows context usage details |
| `/recap` | `/insights` | Shows compact session recap |

### Task & Todo
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/tasks` | `/bashes` | Lists tasks via `GET /api/tasks` |
| `/todo` | — | `add <text>` creates task. `done <id>` completes. `open <id>` shows detail. `list` shows all. |
| `/goal` | — | Shows/sets/clears active goal via `GET/POST /api/goal` |

### Work & Activity
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/work` | — | Shows recent work events from `workspace/work_events/{session_id}.jsonl` |
| `/open` | `/detail` | Opens activity detail in sidebar |
| `/close` | `/panel` | Closes sidebar detail panel |
| `/back` | — | Returns to previous panel (activity→workspace, agent→hive, provider-detail→provider) |

### Agent & Hive
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/agents` | `/agent` | Lists agents via `GET /api/agents`. With arg, sets active agent. |
| `/hive` | — | Opens hive worker list in sidebar |
| `/batch` | — | Starts multi-agent batch workflow |
| `/fork` | — | Forks work to multi-agent flow |
| `/multi-agent` | `/multi_agent` | Multi-agent workflow via `POST /api/multi_agent` |

### Research & Planning
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/deep-research` | — | Submits research task via `/api/multi_agent` (was dead-end, now working) |
| `/ultraplan` | — | Submits high-effort plan via `/api/multi_agent` (was dead-end, now working) |
| `/plan` | — | Switches to plan permission mode |
| `/sandbox` | — | Shows/sets sandbox tier via `GET/POST /api/sandbox` |
| `/effort` | — | Sets reasoning effort mode |

### UI & Display
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/theme` | `/color` | Shows theme/UI config |
| `/statusline` | — | Shows status line settings |
| `/tui` | — | Shows terminal UI renderer info |
| `/output-style` | — | Shows output style config |
| `/scroll-speed` | — | Shows terminal info |
| `/keybindings` | — | Shows keybinding reference |
| `/terminal-setup` | — | Alias for /keybindings |
| `/open-gui` | — | Opens GUI in browser |
| `/gui` | — | `start` launches GUI, `open` opens browser, `build` compiles, `logs` shows logs |
| `/api` | — | `start` launches API server, otherwise shows health |
| `/copy` | — | Copies last assistant response to clipboard |

### Integration Status (Feature Flag Checks)
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/chrome` | — | Shows Chrome integration status |
| `/ide` | `/editor` | Opens VS Code |
| `/background` | `/bg` | Shows background session support |
| `/desktop` | `/app` | Shows desktop handoff support |
| `/mobile` | `/ios`, `/android` | Shows mobile handoff support |
| `/teleport` | `/tp` | Shows teleport support |
| `/remote-control` | `/rc` | Shows remote control support |
| `/remote-env` | — | Shows remote environment support |

### NEXUS Equivalents (Replaced Claude Code Stubs)
| Command | What it shows now | Before fix |
|---------|-------------------|------------|
| `/passes` | Context & usage stats + tips | "Claude Code feature" + docs link |
| `/powerup` | Model, provider, mode, agent counts | "Claude Code feature" + docs link |
| `/privacy-settings` | API key status + security info | "Claude Code feature" + docs link |
| `/radio` | Network status + local endpoints | "Claude Code feature" + docs link |
| `/stickers` | Display/theme config info | "Claude Code feature" + docs link |
| `/upgrade` | Version info + update instructions | "Claude Code feature" + docs link |
| `/usage-credits` | Token usage + local-is-free note | "Claude Code feature" + docs link |

### Other
| Command | Aliases | Behavior |
|---------|---------|----------|
| `/advisor` | — | Shows advisor feature status |
| `/focus` | — | Shows focus view support |
| `/fewer-permission-prompts` | — | Shows permission rules status |
| `/check` | `/test`, `/tests` | `cli` runs tsc check, `py` compiles Python, `gui` builds |
| `/build` | — | `cli` runs tsc check, otherwise builds GUI |
| `/hooks` | — | Shows configured hooks from `.claude/settings.json` |
| `/fast` | — | Toggles fast mode hint |
| `/claude-api` | — | Checks if claude-api skill is installed |
| `/run-skill-generator` | — | Checks if skill-generator skill is installed |
| `/setup-bedrock` | — | Shows Bedrock provider setup instructions |
| `/setup-vertex` | — | Shows Vertex provider setup instructions |
| `/install-github-app` | — | Shows GitHub app setup info |
| `/install-slack-app` | — | Shows Slack app setup info |

## Quick Action Bar

The bottom toolbar shows clickable buttons:
- `[Status]` — submits `/status`
- `[Work]` — submits `/work`
- `[Tasks]` — submits `/todo list`
- `[Hive]` — submits `/hive`
- `[Voice On/Off]` — toggles voice mode dynamically
- `[Git]` — submits `/git`
- `[Diff]` — submits `/diff`
- `[Check]` — submits `/check cli`
- `[Review]` — submits `/review`
- `[GUI]` — submits `/gui start`
- `[Todo+]` — prefills `/todo add `

## Footer Bar

Shows: `~\{dirname}  no sandbox (see /docs)  {provider|auto}`

Provider name is dynamically updated.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Tab | Accept highlighted slash command |
| Up/Down | Navigate slash command palette |
| Enter | Send message |
| Ctrl+C | Exit |
| PageUp / Ctrl+U | Scroll chat up |
| PageDown / Ctrl+D | Scroll chat down |
| Up arrow (empty input) | Scroll chat up one line |
| Down arrow (empty input) | Scroll chat down one line |
| 1-4 (question mode) | Select question option |
