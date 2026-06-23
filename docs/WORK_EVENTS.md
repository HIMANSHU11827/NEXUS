# NEXUS Work Events

Work events track the mission timeline — every file read/write, command run, tool call, and milestone during a NEXUS AI session.

## Storage

Events are stored as JSONL (one JSON object per line):

```
workspace/work_events/<session_id>.jsonl
```

Each line is a self-contained event object:

```json
{"kind": "read", "action": "read", "path": "src/main.py", "target": "src/main.py", "timestamp": 1718000000.0, "session_id": "default"}
{"kind": "write", "action": "edit", "path": "src/main.py", "target": "src/main.py", "timestamp": 1718000001.0, "session_id": "default"}
{"kind": "run", "action": "run", "command": "pytest tests/", "target": "pytest tests/", "timestamp": 1718000002.0, "session_id": "default"}
```

## Event Schema

| Field | Type | Description |
|-------|------|-------------|
| `kind` | string | Event category: `read`, `write`, `run`, `tool`, `search`, `todo`, `mcp`, `terminal`, `milestone` |
| `action` | string | What happened: `read`, `edit`, `create`, `run`, `search`, `add`, `done`, `call`, etc. |
| `path` | string | File path or primary target |
| `target` | string | Secondary target (falls back to `path`, then `action`, then `kind`) |
| `command` | string | Shell command if applicable |
| `tool_name` | string | Tool name if tool-caused |
| `timestamp` | float | Unix epoch seconds |
| `session_id` | string | Session identifier |

## Kind Inference Rules

When an event is appended without an explicit `kind`, it's inferred from:

- `action` == `"read"` → `"read"`
- `action` in (`"edit"`, `"write"`, `"create"`, `"delete"`, `"rename"`, `"patch"`) → `"write"`
- `action` == `"run"` or `command` is set → `"run"`
- `action` == `"search"` → `"search"`
- `action` in (`"add"`, `"done"`, `"update"`) → `"todo"`
- `path` ends with `.md` or `.txt` → `"read"`
- Otherwise → `"run"`

## API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/work-events/{session_id}` | GET | List events for session (returns `{events: [...]}`) |
| `/api/work-events/{session_id}` | POST | Append event (accepts partial event, fills defaults) |

### POST Example

```json
{
  "kind": "write",
  "action": "edit",
  "path": "src/components/App.tsx"
}
```

Response: full event with defaults applied.

## CLI Integration

The CLI `/work` command reads the JSONL file directly:

```
/workspace/work_events/<session_id>.jsonl
```

Shows last 12 events in compact format.

## GUI Integration

The `WorkActivityTimeline` component (`gui/src/components/WorkActivityTimeline.tsx`) renders work events as a real-time scrolling timeline in the GUI sidebar. Events are color-coded by kind and show file paths, command strings, and timestamps.

## Test Coverage

24 tests in `tests/test_work_events.py`:

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestNormalizeWorkEvent` | 13 | Kind inference, action generation, target fallback |
| `TestAppendAndListWorkEvents` | 5 | File persistence, defaults, path format |
| `TestWorkEventApiEndpoints` | 6 | POST/GET endpoints, run-command round-trip, 404 handling |
