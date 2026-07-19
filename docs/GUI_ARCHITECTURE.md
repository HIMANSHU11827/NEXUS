# NEXUS GUI Architecture

The GUI is a React + Vite single-page application backed by a FastAPI Python server. It serves as the visual mission cockpit for NEXUS AI.

## Entry Points

| Component | File | Description |
|-----------|------|-------------|
| API Server | `gui/api.py` | FastAPI backend (~4950 lines) |
| React App | `gui/src/App.tsx` | Main React component |
| Vite Config | `gui/vite.config.ts` | Vite build/dev configuration |

## Starting The GUI

```powershell
python -m nexus --gui     # starts gui.api on :8000 and Vite on :5173
```

For manual development:

```powershell
cd gui
npm install
python -m uvicorn gui.api:app --host 127.0.0.1 --port 8000
npm run dev
```

Or via TUI: `/gui start` launches `scripts/run-gui.ps1`, `/gui open` opens browser.

## Backend (`gui/api.py`)

The FastAPI server provides all REST endpoints consumed by the React GUI. Most are in `gui/api.py`; some (engine, goal, agent, multi-agent, add-dir) are in `server/__init__.py`. Key endpoint groups:

### Session Endpoints
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/sessions` | GET | List all sessions |
| `/api/sessions/new` | POST | Create new session |
| `/api/sessions/load` | POST | Load existing session |
| `/api/sessions/rename` | POST | Rename session |
| `/api/sessions/{id}` | DELETE | Delete session |
| `/api/sessions/active` | GET | Get active session ID |
| `/api/history` | GET | Get session message history |

### Chat & Execution
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/chat` | POST | Send message to agent loop (streaming SSE) |
| `/api/run` | POST | Execute command |
| `/api/multi_agent` | POST | Multi-agent workflow (via server module) |

### Provider & Model
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/providers` | GET | List configured providers |
| `/api/provider` | POST | Set active provider |
| `/api/providers/add` | POST | Add new provider |
| `/api/providers/configure` | POST | Configure provider (key, model, endpoint) |
| `/api/providers/ping` | POST | Test provider endpoint |
| `/api/providers/test` | POST | Test provider credentials |
| `/api/providers/instance/{id}` | DELETE | Remove provider instance |
| `/api/model` | GET/POST | Get/set active model |

### Tools & Registry
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/tools` | GET | List registered tools |
| `/api/skills` | GET | List installed skills |
| `/api/plugins` | GET | List active plugins |
| `/api/mcp` | GET | List MCP servers |
| `/api/manage` | POST | Enable/disable/reload tools, skills, MCP, plugins, providers |

### Status & System
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/status` | GET | Full system status |
| `/api/health` | GET | Health check |
| `/api/features` | GET | Feature flags |
| `/api/version` | GET | Version info |
| `/api/config` | GET | Configuration dump |
| `/api/goal` | GET/POST | Get/set active goal (via server module) |
| `/api/mode` | POST | Switch permission mode |
| `/api/sandbox` | GET/POST | Get/set sandbox tier |
| `/api/agent` | POST | Switch active agent (via server module) |
| `/api/agents` | GET | List agents (via server module) |

### Engine
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/engine/status` | GET | Engine status |
| `/api/engine/config` | POST | Update engine params |
| `/api/engine/compile` | POST | Compile llama.cpp (via server module) |
| `/api/engine/reload` | POST | Hot-reload engine (via server module) |
| `/api/engine/train` | POST | Start fine-tuning (via server module) |
| `/api/engine/train/status` | GET | Training progress (via server module) |

### Security & File
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/files` | GET | Search workspace files |
| `/api/add-dir` | POST | Add working directory (via server module) |
| `/api/secret-scan` | POST | Scan for secrets (Pending implementation) |

### Work Events
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/work-events/{session_id}` | GET | List work events |
| `/api/work-events/{session_id}` | POST | Append work event |

Work events are stored as JSONL (`workspace/work_events/{session_id}.jsonl`). Each event tracks file reads/writes, command runs, tool calls, and mission milestones with timestamps.

## Frontend (`gui/src/`)

| File | Purpose |
|------|---------|
| `App.tsx` | Main app layout with panels |
| `types.ts` | TypeScript interfaces (ActivityItem, WorkEvent, etc.) |
| `textUtils.ts` | Text formatting utilities |
| `index.css` | Global styles (dark theme, MediaPipe overlay, etc.) |
| `components/WorkActivityTimeline.tsx` | Real-time timeline of work events |
| `components/ActivityBar.tsx` | Activity feed panel |
| `components/CanvasPanel.tsx` | Canvas/visualization panel |
| `components/ProviderPanel.tsx` | Provider management panel |

## Security

- The GUI enforces local-only mode by default
- Upload/session sanitization
- Rate limits on API endpoints
- Honest provider status reporting (no fake "connected" states)
- Secret scanner integration

## Vision Integration

The GUI includes MediaPipe Holistic vision (543 landmarks for face, body, hands):
- Real-time camera feed overlay in the GUI
- YOLO object detection/segmentation models
- Face detection via OpenCV Haar cascades
- Memory-efficient model caching

See `docs/MEDIAPIPE_SUITE.md` for full details.
