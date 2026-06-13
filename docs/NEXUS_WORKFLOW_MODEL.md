# NEXUS Workflow Model

This document defines how NEXUS should execute and display work.

The workflow model is built around missions, phases, events, artifacts, and
verification. It is designed to support both a LemonAI-style GUI and a
Claude-Code-style terminal experience from the same backend events.

## User Experience Target

When a user gives NEXUS a large task, they should see:

```text
NEXUS starts mission
  Phase 1: Research & Specification
    Searching docs...
    Reading files...
    Writing todo.md...

  Phase 2: Implementation
    Editing App.tsx...
    Creating API model...
    Running command...

  Phase 3: Verification
    Running tests...
    Building GUI...
    Recording evidence...

NEXUS completes mission
  Summary
  Changed files
  Tests run
  Remaining risks
```

The same mission should appear differently per surface:

- GUI: timeline cards and live computer drawer.
- Terminal: compact phase/event lines.
- CLI: interactive terminal panels.
- Gateway: short status notifications.
- Voice: spoken status and final summary.

## Core Objects

### Mission

A mission is one user goal.

```json
{
  "id": "mis_001",
  "session_id": "default",
  "source": "gui",
  "title": "Improve NEXUS workflow UI",
  "goal": "Make the GUI show LemonAI-style progress",
  "status": "running",
  "created_at": 1780000000.0,
  "updated_at": 1780000020.0
}
```

### Phase

A phase is a visible chunk of work.

```json
{
  "id": "phase_001",
  "mission_id": "mis_001",
  "order": 1,
  "title": "Research & Specification",
  "objective": "Inspect current GUI/API event flow and define target model",
  "status": "done"
}
```

### Work Event

A work event is one observable action.

```json
{
  "id": "evt_001",
  "mission_id": "mis_001",
  "phase_id": "phase_001",
  "kind": "file",
  "action": "Read file",
  "tool": "file_read",
  "target": "gui/src/App.tsx",
  "status": "done",
  "result": "Read 400 lines"
}
```

### Artifact

An artifact is generated output worth opening, replaying, or sharing.

```json
{
  "id": "art_001",
  "mission_id": "mis_001",
  "phase_id": "phase_002",
  "name": "index.html",
  "path": "workspace/artifacts/default/index.html",
  "kind": "html",
  "status": "created"
}
```

### Verification

Verification is the proof that work is real.

```json
{
  "id": "verify_001",
  "mission_id": "mis_001",
  "kind": "test",
  "command": "python -m pytest tests/test_gui_security.py -q",
  "status": "passed",
  "summary": "12 passed"
}
```

## Event Types

Required event types:

```text
mission.started
mission.updated
mission.paused
mission.resumed
mission.failed
mission.completed

phase.created
phase.started
phase.updated
phase.completed
phase.failed

assistant.delta
tool.started
tool.completed
tool.failed

artifact.created
verification.started
verification.completed
memory.learned
evidence.recorded
```

## Standard Phase Pattern

NEXUS should default to this phase pattern for engineering tasks:

```text
Phase 1: Understand
  Inspect repo, docs, user goal, constraints, and related files.

Phase 2: Plan
  Create todo list, identify files, choose verification path.

Phase 3: Implement
  Edit files, create artifacts, run commands.

Phase 4: Verify
  Run tests/builds/diagnostics, inspect failures, repair if needed.

Phase 5: Report
  Summarize changes, evidence, risk, and next steps.
```

For research tasks:

```text
Research -> Compare -> Synthesize -> Artifact -> Evidence
```

For automation tasks:

```text
Prepare -> Execute -> Monitor -> Recover -> Report
```

For GUI/build tasks:

```text
Inspect -> Design -> Implement -> Build -> Visual Check -> Report
```

## GUI Behavior

The GUI should render phases as first-class timeline sections.

```text
Phase 1: Understand
  [Read file] gui/src/App.tsx
  [Search] workEvents
  [Read file] gui/api.py

Phase 2: Implement
  [Edit file] core/mission/models.py
  [Edit file] gui/src/App.tsx

Phase 3: Verify
  [Run command] npm run build
```

Clicking any event opens the right-side computer drawer.

Computer drawer modes:

- Editor: file preview.
- Terminal: command output.
- Browser: web/browser automation view.
- Artifact: generated file preview.
- Replay: older event snapshot.

The drawer title should describe the current action:

```text
NEXUS is using Editor
Performing App.tsx
```

## Terminal Behavior

Terminal output should stay compact and readable:

```text
[MISSION] Improve NEXUS workflow UI
[PHASE 1/5] Understand
  done  Read file      gui/src/App.tsx
  done  Search         workEvents

[PHASE 2/5] Implement
  run   Edit file      core/mission/models.py
  done  Edit file      gui/api.py

[VERIFY]
  done  python -m pytest tests/test_gui_security.py -q

[DONE] 3 files changed, 1 check passed
```

## Gateway Behavior

Gateway channels should not receive noisy logs. They should receive status
summaries:

```text
NEXUS started: Improve workflow UI
Phase 1 done: inspected GUI/API event flow
Phase 2 running: editing mission models
Verification failed: npm run build
NEXUS repaired the issue and build passed
Mission complete: 3 files changed, 2 checks passed
```

## Pause, Continue, Stop

All surfaces should support the same controls:

- `pause`: stop after current safe point.
- `continue`: resume from latest checkpoint.
- `stop`: abort current mission and mark incomplete.
- `status`: show current phase and latest event.
- `replay`: show mission timeline.

The backend should persist enough state to resume:

```text
mission.json
phases.jsonl
events.jsonl
checkpoints.jsonl
artifacts/
```

## Verification Policy

NEXUS should choose verification based on touched files:

- Python source: `python -m compileall` and related pytest files.
- GUI source: `cd gui && npm run build`.
- API changes: targeted backend tests and import checks.
- Tool changes: relevant `tests/test_*tool*.py`.
- Docs-only changes: no test required unless links/generation changed.

Verification events must be shown in the timeline and final answer.

## Final Report Contract

Every completed mission should end with:

```text
What changed
Files touched
Commands run
Verification result
Evidence/artifacts
Remaining risk
```

For failed or paused missions:

```text
What completed
Where it stopped
Why it stopped
What is safe to resume
Suggested next action
```

