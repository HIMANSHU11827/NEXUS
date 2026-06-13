# NEXUS Unified Agent Architecture

This document defines the target architecture for NEXUS as one autonomous agent
platform across terminal, CLI, GUI, gateway channels, browser, tools, memory,
voice, vision, and long-running missions.

NEXUS should feel like one system with many surfaces:

- Claude Code style terminal coding: read the repo, edit files, run commands, test, and explain.
- LemonAI style visual workflow: phases, live work rows, file preview, realtime computer panel.
- OpenClaw style gateway: WhatsApp, Telegram, Discord, and other channels route into the same agent core.
- Manus style asynchronous execution: decompose big tasks, continue in the background, notify when done.
- Hermes style growth: remember failures, promote reusable skills, and improve future missions.

The goal is not to copy any one agent. The goal is to make NEXUS the local-first
engineering operating layer where all interfaces share one mission runtime.

## North Star

NEXUS accepts a mission from any surface, turns it into phases, executes tools,
shows live progress, verifies the result, stores evidence, learns from outcomes,
and gives the user a replayable final report.

```text
User
  -> Terminal | CLI | GUI | Gateway  (any of the four)
  -> Unified Mission Runtime
  -> Planner -> Phase Engine -> Executor -> Verifier -> Memory
  -> Tools: shell, files, browser, search, RAG, Hive, diagnostics, rollback
  -> Evidence, artifacts, work events, mission replay
  -> Final answer + timeline + resumable state
```

## Four User Surfaces

A user can send a mission from **any** of these four surfaces. All four feed the same
agent core (`orchestrators/loop.py` today; `core/mission/` as the wrapper matures).

| Surface | Path | Role |
|---------|------|------|
| **Terminal** | `nexus.py`, `shell.py` | Live operator shell. Direct `NexusLoop` — the real in-process runtime. **Not** the Ink CLI. |
| **CLI** | `cli/nexus-cli.tsx` | TypeScript Ink thin client over `gui/api.py` (`localhost:8000/api`). |
| **GUI** | `gui/api.py`, `gui/src/App.tsx` | Visual mission cockpit and local FastAPI control plane. |
| **Gateway** | `gateway/` | External channels (Telegram, Discord, WhatsApp, Meta) into the same runtime. |

Rules:

- The user may start work from terminal, CLI, GUI, or gateway interchangeably.
- Surfaces must not fork separate agent brains; they normalize requests into one mission runtime.
- Terminal is the standalone live path (`python nexus.py`). CLI and GUI require the API unless terminal is used.
- Voice (`voice_chat.py`) and MCP/API are additional surfaces, not a fifth primary user channel.

### Internally connected surfaces

The four surfaces are **one linked system**, not four isolated apps. If a user starts
a mission in the GUI, the same session id, chat history, and work-event timeline must
be visible from terminal, CLI, and gateway (compact form).

Shared state bus (local files today):

| Store | Path | Contents |
|-------|------|----------|
| Active session | `workspace/active_session.json` | Current linked session for all four surfaces |
| Session memory | `logs/sessions/{session_id}.json` | Conversation + loop memory |
| Work events | `workspace/work_events/{session_id}.jsonl` | Mission timeline (tools, files, commands) |
| Session meta | `logs/sessions/{session_id}.meta` | Title and session labels |

Implementation: `core/session_bus.py` + `/api/sessions/active`.

Connection rules:

- Use the **same `session_id`** on every surface (`default`, `session_173…`, or `gateway_{platform}_{chat_id}`).
- Any surface that chats or switches session updates `active_session.json`.
- GUI and CLI sync through `gui/api.py` (`/api/sessions/active`, `/api/work-events`).
- Terminal auto-joins the active session on start and calls `sync_memory` before each reply.
- Gateway maps each chat to a stable session id on the same bus.
- A mission started on any surface must be observable and continuable on the others without re-sending the prompt.

## Primary Runtime Layers

### 1. Interface Layer

Most entry points are thin clients. They should not contain separate agent logic.
**Terminal is the exception**: it runs `NexusLoop` in-process via `shell.py`.

- `nexus.py` and `shell.py`: **Terminal** — live, direct operator interface.
- `cli/`: **CLI** — TypeScript/Ink UI (API client, not the live terminal).
- `gui/api.py`: local FastAPI control plane for CLI and GUI.
- `gui/src/App.tsx`: **GUI** — visual mission cockpit.
- `gateway/`: **Gateway** — Telegram, WhatsApp, Discord, webhooks, and future channels.
- `voice_chat.py` and `core/voice/`: speech input/output surface (supplementary).

Each surface sends the same normalized request:

```json
{
  "source": "gui",
  "session_id": "default",
  "operator_id": "local",
  "prompt": "Build the feature and verify it",
  "mode": "agent",
  "constraints": {},
  "attachments": []
}
```

### 2. Mission Runtime

The Mission Runtime is the new center of gravity. It should wrap the current
`NexusLoop` instead of replacing it all at once.

Core responsibilities:

- Create mission records.
- Generate and update phases.
- Attach every tool call to a phase.
- Persist work events.
- Track pause/resume/cancel state.
- Expose one event stream for GUI, terminal, CLI, and gateway.
- Summarize outcomes and verification evidence.

Target modules:

```text
core/mission/
  models.py        # Mission, Phase, WorkEvent, Artifact, Checkpoint
  engine.py        # MissionEngine orchestration wrapper
  store.py         # JSONL/SQLite persistence boundary
  phases.py        # phase inference and todo shaping
  stream.py        # normalized event stream
  controls.py      # pause, resume, stop, continue
```

### 3. Reasoning Layer

The current `orchestrators/loop.py` remains the brain loop, but it should emit
structured mission events instead of only plain stream text.

Responsibilities:

- Build system prompt and repo grounding.
- Call model provider.
- Extract tool calls.
- Ask Hive for broad mission delegation.
- Compact context.
- Trigger self-correction after failures.

The loop should eventually return structured events:

```text
assistant.delta
mission.started
phase.started
tool.started
tool.completed
artifact.created
verification.started
mission.completed
mission.paused
mission.failed
```

### 4. Tool Execution Layer

`tools/nexus_tools/registry.py` remains the executable capability layer.

Every tool execution should produce a `WorkEvent`:

```json
{
  "id": "evt_...",
  "mission_id": "mis_...",
  "phase_id": "phase_...",
  "kind": "file",
  "action": "Edit file",
  "tool": "file_edit",
  "target": "gui/src/App.tsx",
  "status": "done",
  "result": "Updated timeline renderer",
  "preview_path": "gui/src/App.tsx"
}
```

Read-only tools can run in parallel. Write tools stay serial unless a phase
explicitly proves they do not overlap.

### 5. Safety, Evidence, And Recovery

NEXUS should favor fast autonomous work, but every meaningful action must be
observable and recoverable.

Required guardrails:

- Risk score shell/file/git/process actions.
- Create rollback or patch ledger entries before high-impact edits.
- Keep workspace path boundaries.
- Record command output and file previews.
- Attach verification commands to mission evidence.
- Convert failures into failure memory and future regression plans.

Existing systems to preserve:

- `core/world_model.py`
- `core/autonomy/`
- `core/os_power/`
- `optimization/mission_replay.py`
- `tools/nexus_tools/advanced_power_tool.py`
- `core/security/secret_scanner.py`

### 6. Memory And Self-Improvement

NEXUS should learn from missions without polluting the repo with runtime data.

Memory flow:

```text
Mission outcome
  -> evidence ledger
  -> failure memory
  -> adaptive memory graph
  -> reusable strategy
  -> optional skill proposal
  -> future prompt/context packet
```

Memory should store facts, decisions, failures, and verified tactics. It should
not store unsupported bragging or unverified claims.

### 7. Visual Mission Cockpit

The GUI should become the operator cockpit.

Center panel:

- Conversation.
- Mission title.
- Collapsible phases.
- Tool/action rows under each phase.
- Status badges: running, done, failed, paused.

Right panel:

- "NEXUS's computer".
- Live file preview.
- Terminal output.
- Browser preview.
- Artifact preview.
- Realtime/playback controls.

Left panel:

- Sessions.
- Agents/Hive.
- Library/skills.
- Tools/plugins.
- Providers.

Bottom composer:

- Prompt.
- Mode selector.
- Provider/agent selector.
- Attachments.
- Continue, pause, stop, resume controls.

### 8. Gateway Runtime

Gateway channels should share the same mission state, but receive compact updates.

Example Telegram/WhatsApp update:

```text
Mission: Build GUI workflow
Phase 2 running: Editing App.tsx
Last action: Run command npm run build
Status: waiting for verification
```

Gateway channels should support:

- Start mission.
- Continue mission.
- Pause/stop mission.
- Ask for status.
- Receive final report.
- Open GUI link for full replay.

## Canonical Mission Lifecycle

```text
1. Intake
   Normalize request from GUI, terminal, CLI, gateway, voice, or API.

2. Context Build
   Load NEXUS.md, repo map, session memory, RAG, provider health, and constraints.

3. Mission Create
   Persist mission id, source, session, title, user goal, and initial state.

4. Plan
   Create phases and todo list. Use Hive for broad work.

5. Execute
   Run tool calls. Emit work events. Update phase status.

6. Observe
   Feed tool results back into the loop. Detect errors and changed files.

7. Verify
   Run targeted tests, compile checks, diagnostics, gui build, or custom checks.

8. Recover
   On failure, use self-correction, rollback, patch ledger, and failure memory.

9. Complete
   Produce final answer with changed files, commands run, tests, and evidence.

10. Learn
   Store verified lessons, failure vaccines, useful strategies, and artifacts.
```

## Event Contract

All surfaces should consume one event shape.

```json
{
  "id": "evt_001",
  "type": "tool.completed",
  "mission_id": "mis_001",
  "phase_id": "phase_002",
  "session_id": "default",
  "source": "gui",
  "timestamp": 1780000000.0,
  "status": "done",
  "kind": "command",
  "title": "Run tests",
  "action": "Run command",
  "tool": "bash",
  "target": "python -m pytest tests/test_gui_security.py -q",
  "result": "12 passed",
  "preview": "",
  "metadata": {}
}
```

The existing `[NEXUS_ACTIVITY]` stream marker can remain as a compatibility
transport, but the payload should follow this contract.

## Implementation Roadmap

### Phase A: Mission Data Model

- Add `core/mission/models.py`.
- Add `core/mission/store.py`.
- Store missions in `workspace/missions/`.
- Keep existing `workspace/work_events/` compatibility.

### Phase B: Loop Integration

- Wrap `NexusLoop.stream_run()` with `MissionEngine.run_stream()`.
- Emit `mission.started`, `phase.started`, `tool.started`, `tool.completed`.
- Infer active phase from plan/todo/tool context.

### Phase C: GUI Upgrade

- Replace generic "Working" blocks with mission phases.
- Auto-open the computer drawer for file, command, browser, and artifact events.
- Add pause, stop, continue, and resume controls.
- Add mission replay view.

### Phase D: Terminal And CLI Parity

- Render the same mission events in terminal text mode.
- Add concise phase rows to the Ink CLI.

### Phase E: Gateway Parity

- Route gateway messages to `MissionEngine`.
- Send compact phase/status notifications.
- Support continue/pause/status commands.

### Phase F: Verification And Learning

- Attach test results to mission evidence.
- Feed failures into failure memory.
- Promote successful repeated workflows into skills.

## Non-Negotiable Design Rules

- One mission runtime; many interfaces.
- Structured events first, pretty UI second.
- GUI must never invent progress.
- Terminal and gateway must see the same truth as GUI.
- Every file edit and command should be replayable.
- Long missions must checkpoint and resume.
- Runtime/generated data stays in `workspace/`, `logs/`, or configured stores.
- Claims must be backed by code, output, tests, or evidence.

