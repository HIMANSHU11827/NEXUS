# GUI

FastAPI backend + React operator surface — visual mission cockpit for NEXUS AI.

**Version:** 1.0.0

## Usage
```powershell
python -m nexus --gui
```

Manual backend-only development:

```powershell
python -m uvicorn gui.api:app --host 127.0.0.1 --port 8000
cd gui
npm run dev
```

## Features
- Mission timeline and work event viewer
- `/api/work-events` cursor replay for canonical public activity events
- `/api/runs` and `/api/runs/{session_id}/{run_id}` for durable run context plus public event replay
- Chat requests use canonical SSE event streaming; the Stop control calls backend cancellation before aborting the browser stream
- GUI command execution records shared permission decisions and still runs through risk scoring plus sandbox workspace checks
- Provider health status and configuration via `config/nexus_config.yaml`; masked key placeholders do not overwrite saved credentials
- Audit control plane for unified graph, evidence, and tool economy
