import os
import asyncio
import json
import yaml
import re
import shutil
import time
import threading
import concurrent.futures
import queue
import subprocess
import sys
import uuid
import zipfile
import urllib.request
from io import BytesIO
from urllib.parse import urlparse
from typing import List, Dict, Any
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
# 🌌 [NEXUS_PATH_CORE]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
from orchestrators.loop import NexusLoop
_UPLOAD_DIR = os.path.join(_ROOT, "workspace", "uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)
_WORK_EVENTS_DIR = os.path.join(_ROOT, "workspace", "work_events")
os.makedirs(_WORK_EVENTS_DIR, exist_ok=True)
_ARTIFACTS_DIR = os.path.join(_ROOT, "workspace", "artifacts")
os.makedirs(_ARTIFACTS_DIR, exist_ok=True)
_REMINDERS_PATH = os.path.join(_ROOT, "workspace", "dashboard_reminders.json")
_SOURCE_LIBRARY_PATH = os.path.join(_ROOT, "workspace", "source_library.json")
_API_AUDIT_LOG = os.path.join(_ROOT, "logs", "dashboard_api.jsonl")
_LOCAL_ONLY = os.environ.get("NEXUS_DASHBOARD_LOCAL_ONLY", "true").lower() == "true"
_AUTH_TOKEN = os.environ.get("NEXUS_DASHBOARD_TOKEN", "").strip()
_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT = int(os.environ.get("NEXUS_DASHBOARD_RATE_LIMIT", "240"))
_RATE_BUCKETS: Dict[str, List[float]] = {}
_MAX_UPLOAD_BYTES = int(os.environ.get("NEXUS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
_ALLOWED_UPLOAD_EXTS = {".txt", ".md", ".json", ".py", ".js", ".ts", ".tsx", ".css", ".yaml", ".yml", ".csv", ".log"}
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_SHOW_CHAT_THINKING = os.environ.get("NEXUS_CHAT_SHOW_THINKING", "false").lower() in {"1", "true", "yes", "on"}

app = FastAPI()

# 🌌 [CORS_POLICY]: Consolidated and standardized for high-fidelity communication.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("NEXUS_DASHBOARD_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 Cognitive Pool: Track loops by session ID
_LOOPS: Dict[str, NexusLoop] = {}
_THREAD_LOCAL = threading.local()


def audit_event(request: Request, status: str, detail: str = "") -> None:
    try:
        os.makedirs(os.path.dirname(_API_AUDIT_LOG), exist_ok=True)
        record = {
            "time": time.time(),
            "client": request.client.host if request.client else "unknown",
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "detail": detail[:500],
        }
        with open(_API_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def require_config_write_allowed(request: Request) -> None:
    from authentication import validate_dashboard_token
    supplied = request.headers.get("x-nexus-token", "")
    if not validate_dashboard_token(supplied):
        raise HTTPException(status_code=401, detail="Invalid dashboard token")
    if _LOCAL_ONLY and request.client and request.client.host not in _LOCAL_CLIENTS:
        raise HTTPException(status_code=403, detail="Dashboard config writes are local-only")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    if _LOCAL_ONLY and client not in _LOCAL_CLIENTS:
        audit_event(request, "blocked", "non-local client")
        return JSONResponse({"detail": "Dashboard is local-only"}, status_code=403)

    now = time.time()
    bucket = [t for t in _RATE_BUCKETS.get(client, []) if now - t < _RATE_WINDOW_SECONDS]
    bucket.append(now)
    _RATE_BUCKETS[client] = bucket
    if len(bucket) > _RATE_LIMIT:
        audit_event(request, "blocked", "rate limit")
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

    response = await call_next(request)
    audit_event(request, str(response.status_code))
    return response


def safe_session_id(session_id: str) -> str:
    """Return a filesystem-safe session id."""
    raw = os.path.basename(str(session_id or "default")).replace(".json", "")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return cleaned or "default"


def session_file_path(session_id: str, suffix: str = ".json") -> str:
    sessions_dir = os.path.join(_ROOT, "logs", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    safe_id = safe_session_id(session_id)
    path = os.path.abspath(os.path.join(sessions_dir, f"{safe_id}{suffix}"))
    root = os.path.abspath(sessions_dir)
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return path


def safe_upload_path(filename: str) -> str:
    safe_name = os.path.basename(str(filename or "upload.bin"))
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", safe_name).strip("._") or "upload.bin"
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(status_code=400, detail=f"Upload type not allowed: {ext or 'none'}")
    upload_root = os.path.abspath(_UPLOAD_DIR)
    path = os.path.abspath(os.path.join(upload_root, safe_name))
    if os.path.commonpath([upload_root, path]) != upload_root:
        raise HTTPException(status_code=400, detail="Invalid upload filename")
    return path


def load_source_library() -> List[Dict[str, Any]]:
    try:
        if not os.path.exists(_SOURCE_LIBRARY_PATH):
            return []
        with open(_SOURCE_LIBRARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def save_source_library(sources: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_SOURCE_LIBRARY_PATH), exist_ok=True)
    with open(_SOURCE_LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2)


def upsert_source_library(item: Dict[str, Any]) -> Dict[str, Any]:
    sources = load_source_library()
    source_id = str(item.get("id") or f"src_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}")
    normalized = {
        "id": source_id,
        "name": str(item.get("name") or "Untitled source")[:180],
        "type": "Website" if str(item.get("type")).lower() == "website" else "File",
        "checked": bool(item.get("checked", True)),
        "path": str(item.get("path") or ""),
        "url": str(item.get("url") or ""),
        "created_at": float(item.get("created_at") or time.time()),
        "updated_at": time.time(),
    }
    sources = [src for src in sources if str(src.get("id")) != source_id]
    sources.insert(0, normalized)
    save_source_library(sources)
    return normalized


def update_source_library(source_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    sources = load_source_library()
    for index, item in enumerate(sources):
        if str(item.get("id")) == source_id:
            item = dict(item)
            if "name" in patch:
                item["name"] = str(patch.get("name") or item.get("name") or "Untitled source")[:180]
            if "checked" in patch:
                item["checked"] = bool(patch.get("checked"))
            item["updated_at"] = time.time()
            sources[index] = item
            save_source_library(sources)
            return item
    raise HTTPException(status_code=404, detail="Source not found")


def delete_source_library(source_id: str) -> None:
    sources = load_source_library()
    next_sources = [item for item in sources if str(item.get("id")) != source_id]
    if len(next_sources) == len(sources):
        raise HTTPException(status_code=404, detail="Source not found")
    save_source_library(next_sources)


def safe_workspace_read_path(raw_path: str) -> str:
    value = str(raw_path or "").strip().strip('"').strip("'")
    if not value:
        raise HTTPException(status_code=400, detail="Path is required")
    if not os.path.isabs(value):
        value = os.path.join(_ROOT, value)
    path = os.path.abspath(value)
    root = os.path.abspath(_ROOT)
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(status_code=400, detail="Path is outside the NEXUS workspace")
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return path


def work_events_path(session_id: str) -> str:
    sid = safe_session_id(session_id)
    path = os.path.abspath(os.path.join(_WORK_EVENTS_DIR, f"{sid}.jsonl"))
    if os.path.commonpath([os.path.abspath(_WORK_EVENTS_DIR), path]) != os.path.abspath(_WORK_EVENTS_DIR):
        raise HTTPException(status_code=400, detail="Invalid session id")
    return path


def safe_artifact_name(raw_name: str, lang: str = "txt") -> str:
    name = os.path.basename(str(raw_name or "").strip() or "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    ext_map = {"html": "html", "htm": "html", "tsx": "tsx", "jsx": "jsx", "ts": "ts", "js": "js", "python": "py", "py": "py", "css": "css", "json": "json"}
    ext = ext_map.get(str(lang or "").lower(), "txt")
    if not name:
        name = f"artifact.{ext}"
    if "." not in name:
        name = f"{name}.{ext}"
    return name[:120]


def update_todo_file_and_states(session_id: str, new_event: Dict[str, Any], turn_id: str = "") -> List[Dict[str, Any]]:
    if new_event.get("role") == "planning_artifact" or new_event.get("kind") == "todo":
        return []
    sid = safe_session_id(session_id)
    events = list_work_events(sid, limit=1000, active_turn_id=turn_id)
    if turn_id:
        events = [e for e in events if str(e.get("turn_id", "")) == turn_id]
    todo_events = [e for e in events if e.get("kind") == "todo" and e.get("phase_index") is not None]
    if not todo_events:
        return []
    
    # Sort todo events by phase_index
    todo_events.sort(key=lambda x: int(x.get("phase_index") or 0))
    
    kind = str(new_event.get("kind") or "").lower()
    status = str(new_event.get("status") or "").lower()
    target = str(new_event.get("target") or "").lower()
    
    # Find phase indexes by checking title keywords
    research_idx = 1
    impl_idx = 2
    verify_idx = len(todo_events)
    
    for i, e in enumerate(todo_events, 1):
        title_lower = str(e.get("title") or "").lower()
        if any(w in title_lower for w in ["research", "spec", "analyze", "design", "plan"]):
            research_idx = i
        if any(w in title_lower for w in ["implement", "code", "write", "create", "build", "develop", "patch"]):
            impl_idx = i
        if any(w in title_lower for w in ["verify", "test", "check", "run", "compile"]):
            verify_idx = i
            
    is_explicit = False
    target_lower = str(target).lower()
    basename = os.path.basename(target_lower)
    for e in todo_events:
        for item in (e.get("items") or []):
            item_lower = str(item).lower()
            if target_lower in item_lower or (basename and basename in item_lower):
                is_explicit = True
                break
        if is_explicit:
            break
            
    if target_lower.endswith("todo.md") or kind == "todo":
        is_explicit = True

    if not is_explicit:
        return []

    if kind in ["search", "rag"]:
        active_phase_index = research_idx
    elif kind == "file":
        active_phase_index = impl_idx
    elif kind == "command":
        active_phase_index = verify_idx
    else:
        active_phase_index = research_idx
        
    updated_events = []
    changes_made = False
    
    # Update checked items for the current active phase
    for e in todo_events:
        idx = int(e.get("phase_index") or 1)
        if idx == active_phase_index and status == "done":
            items = e.get("items") or []
            checked_items = e.get("checked_items") or []
            unchecked = [item for item in items if item not in checked_items]
            if unchecked:
                checked_items.append(unchecked[0])
                e["checked_items"] = checked_items
                changes_made = True

    # Mark phases as done if all their items are checked
    first_incomplete_idx = None
    for e in todo_events:
        idx = int(e.get("phase_index") or 1)
        items = e.get("items") or []
        checked = e.get("checked_items") or []
        if len(checked) >= len(items) and len(items) > 0:
            if e.get("status") != "done":
                e["status"] = "done"
                changes_made = True
        else:
            if first_incomplete_idx is None:
                first_incomplete_idx = idx

    actual_active_index = first_incomplete_idx if first_incomplete_idx is not None else len(todo_events)
    
    # Propagate state changes to the phases
    for e in todo_events:
        idx = int(e.get("phase_index") or 1)
        current_status = e.get("status", "pending")
        if idx < actual_active_index:
            new_status = "done"
        elif idx == actual_active_index:
            new_status = "running"
        else:
            new_status = "pending"
            
        if new_status != current_status:
            e["status"] = new_status
            changes_made = True
            
        if changes_made or idx == active_phase_index:
            updated_events.append(e)
            
    # Generate updated todo.md content
    prompt_text = todo_events[0].get("task", "Agent Workspace Plan")
    lines = ["## TODO List", "", f"Task: {prompt_text}", ""]
    
    for e in todo_events:
        idx = e.get("phase_index")
        title = e.get("title")
        items = e.get("items") or []
        checked = e.get("checked_items") or []
        
        phase_done = e.get("status") == "done"
        phase_running = e.get("status") == "running"
        
        box = "[x]" if phase_done else "[/]" if phase_running else "[ ]"
        lines.append(f"- {box} Phase {idx}: {title}")
        
        for item in items:
            item_box = "[x]" if item in checked or phase_done else "[ ]"
            lines.append(f"  - {item_box} {item}")
            
    todo_content = "\n".join(lines).strip() + "\n"
    todo_rel_path = write_workspace_todo_plan(todo_content)
    
    # Build a file event for todo.md to update the editor preview on frontend
    todo_file_event = {
        "kind": "file",
        "type": "file",
        "action": "Edit file",
        "title": "todo.md",
        "task": prompt_text,
        "target": todo_rel_path,
        "path": todo_rel_path,
        "preview": todo_content,
        "status": "done",
        "turn_id": turn_id,
        "phase": f"Phase {actual_active_index}: {todo_events[actual_active_index-1].get('title') if actual_active_index <= len(todo_events) else 'Work'}",
        "phase_index": actual_active_index,
        "role": "planning_artifact",
    }
    
    updated_events.append(todo_file_event)
    
    # Persist updated events to session work events log
    for event in updated_events:
        append_work_event(sid, event)
        
    return updated_events

def normalize_work_event_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = dict(payload or {})
    raw_kind = str(event.get("kind") or event.get("type") or "").lower()
    raw_action = str(event.get("action") or event.get("title") or "").lower()
    raw_tool = str(event.get("tool") or event.get("name") or "").lower()

    if raw_kind == "artifact":
        kind = "file"
    elif "rag" in raw_kind or "rag" in raw_action or "retrieval" in raw_action or "atlas" in raw_tool:
        kind = "rag"
    elif "mcp" in raw_kind or "mcp" in raw_action or "mcp" in raw_tool:
        kind = "mcp"
    elif "browser" in raw_kind or "browser" in raw_action or "browser" in raw_tool:
        kind = "browser"
    elif any(token in raw_kind for token in ("search", "web")) or "search" in raw_action or any(token in raw_tool for token in ("search", "grep", "glob")):
        kind = "search"
    elif any(token in raw_kind for token in ("command", "bash", "terminal", "shell", "exec")) or event.get("command"):
        kind = "command"
    elif "file" in raw_kind or "file" in raw_action or "file" in raw_tool or event.get("path"):
        kind = "file"
    elif "skill" in raw_kind:
        kind = "skill"
    elif "plugin" in raw_kind:
        kind = "plugin"
    elif "provider" in raw_kind:
        kind = "provider"
    elif any(token in raw_kind for token in ("hive", "agent", "worker")):
        kind = "hive"
    elif "todo" in raw_kind:
        kind = "todo"
    else:
        kind = raw_kind or "tool"

    action = str(event.get("action") or event.get("title") or "").strip()
    if not action:
        if kind == "file":
            if any(token in raw_action for token in ("delete", "remove")):
                action = "Delete file"
            elif any(token in raw_action for token in ("create", "write")):
                action = "Create file"
            elif any(token in raw_action for token in ("read", "view")):
                action = "Read file"
            elif "update" in raw_action:
                action = "Update file"
            else:
                action = "Edit file"
        elif kind == "search":
            action = "Searching"
        elif kind == "rag":
            action = "Read context"
        elif kind == "mcp":
            action = "Use MCP"
        elif kind == "browser":
            action = "Browse"
        elif kind == "command":
            action = "Run command"
        elif kind == "skill":
            action = "Use skill"
        elif kind == "plugin":
            action = "Use plugin"
        elif kind == "provider":
            action = "Check provider"
        elif kind == "hive":
            action = "Delegate task"
        elif kind == "todo":
            action = "Plan work"
        else:
            action = "Use tool"

    target = (
        event.get("target")
        or event.get("path")
        or event.get("command")
        or event.get("query")
        or event.get("tool")
        or event.get("name")
        or event.get("result")
        or ""
    )
    event["kind"] = kind
    event["type"] = kind
    event["action"] = action
    event.setdefault("title", action)
    if target:
        event["target"] = target
    return event

def append_work_event(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    event = normalize_work_event_payload(payload)
    event.setdefault("id", f"evt_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}")
    event["session_id"] = safe_session_id(session_id)
    event.setdefault("created_at", time.time())
    event.setdefault("type", event.get("kind") or event.get("tool") or "tool")
    event.setdefault("title", event.get("action") or event.get("tool") or "Work event")
    event.setdefault("target", event.get("path") or event.get("target") or event.get("command") or "")
    event.setdefault("status", "running")
    target = str(event.get("target") or event.get("path") or "")
    if (event.get("kind") == "file" or event.get("type") == "file") and target:
        try:
            file_path = safe_workspace_read_path(target)
            event["path"] = os.path.relpath(file_path, _ROOT)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                event["preview"] = f.read(20000)
        except Exception as exc:
            event["preview_error"] = str(exc)
    os.makedirs(_WORK_EVENTS_DIR, exist_ok=True)
    with open(work_events_path(session_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
    if hasattr(_THREAD_LOCAL, "appended_events"):
        _THREAD_LOCAL.appended_events.append(event)
        
    if event.get("kind") not in ("todo", "planning_artifact") and event.get("role") != "planning_artifact":
        try:
            update_todo_file_and_states(session_id, event, event.get("turn_id", ""))
        except Exception as e:
            print(f"[API_ERROR]: Failed to update todo.md/states: {e}")
            
    return event


def parse_todo_markdown(content: str) -> List[Dict[str, Any]]:
    plan = []
    current_phase = None
    
    for line in content.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
            
        # Match phase line: "- [ ] Phase 1: Research & Spec" or "- [x] Phase 2: Code" or "- [/] Phase 3..."
        phase_match = re.match(r"^-\s*(?:\[([ x/])\]\s*)?Phase\s+(\d+):\s*(.*)", line_str, re.IGNORECASE)
        if phase_match:
            box = phase_match.group(1) or " "
            phase_idx = int(phase_match.group(2))
            title = phase_match.group(3).strip()
            
            status = "done" if box == "x" else "running" if box == "/" else "pending"
            
            current_phase = {
                "phase_index": phase_idx,
                "title": title,
                "status": status,
                "items": [],
                "checked_items": []
            }
            plan.append(current_phase)
            continue
            
        # Match sub-item line: "  - [ ] sub-task"
        item_match = re.match(r"^\s*-\s*\[([ x/])\]\s*(.*)", line)
        if item_match and current_phase:
            box = item_match.group(1) or " "
            item_text = item_match.group(2).strip()
            current_phase["items"].append(item_text)
            if box == "x":
                current_phase["checked_items"].append(item_text)
                
    # Normalize phase indices so they are always sequential starting from 1
    for idx, phase in enumerate(plan, start=1):
        phase["phase_index"] = idx
        
    return plan


def build_workflow_plan(prompt: str) -> List[Dict[str, Any]]:
    task = str(prompt or "").strip()
    lowered = task.lower()
    
    # Attempt dynamic LLM plan generation with a strict 3.5 seconds timeout
    def generate_plan():
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel(_ROOT)
            
            system_instructions = (
                "You are the NEXUS AI Architect. Analyze the user's request and create a detailed, "
                "phase-by-phase implementation plan (todo list) for the agent.\n"
                "Output ONLY a raw JSON array of phases. Do NOT wrap it in ```json blocks or include any extra commentary. Just the raw JSON.\n"
                "Each phase must have:\n"
                "- \"title\": A concise phase name (e.g. 'Research & Spec')\n"
                "- \"items\": An array of 3-5 specific sub-tasks to execute during this phase.\n"
                "Keep the JSON valid."
            )
            
            user_prompt = f"User Request: {prompt}\n\nGenerate the plan JSON:"
            
            response = kernel.moe.generate(
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response
        except Exception as e:
            print(f"[API_WARN]: Failed inside plan thread: {e}")
            return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(generate_plan)
            response = future.result(timeout=15.0)
            if response:
                raw_response = response.strip()
                json_match = re.search(r"(\[[\s\S]*\])", raw_response)
                if json_match:
                    raw_response = json_match.group(1)
                    
                plan = json.loads(raw_response)
                if isinstance(plan, list) and len(plan) > 0:
                    cleaned_plan = []
                    for phase in plan:
                        if isinstance(phase, dict) and "title" in phase:
                            title = phase["title"]
                            title = re.sub(r"^Phase\s+\d+:\s*", "", title, flags=re.IGNORECASE)
                            items = phase.get("items", [])
                            if not isinstance(items, list):
                                items = [str(items)]
                            cleaned_plan.append({
                                "title": title,
                                "items": [str(i).strip() for i in items if str(i).strip()]
                            })
                    if cleaned_plan:
                        return cleaned_plan
    except Exception as e:
        print(f"[API_WARN]: Dynamic LLM plan generation timed out or failed: {e}")

    # Fallback heuristics:
    if re.search(r"\b(dino|dinosaur|game|playable|runner|platformer|snake|puzzle)\b", lowered):
        return [
            {
                "title": "Understand the requested playable game",
                "items": ["Identify game type", "Choose file format", "Decide verification path"],
            },
            {
                "title": "Create the game file in the workspace",
                "items": ["Generate playable code", "Save artifact file", "Open file preview"],
            },
            {
                "title": "Run a real verification command",
                "items": ["Compile/check syntax", "Capture command result", "Surface errors if any"],
            },
        ]
    if re.search(r"\b(fix|bug|broken|not working|error|crash|issue|problem|wrong|fail|failing)\b", lowered):
        return [
            {
                "title": "Understand the broken behavior",
                "items": ["Restate the failure", "Locate visible symptoms", "Choose likely area"],
            },
            {
                "title": "Inspect the related code and logs",
                "items": ["Read relevant files", "Check runtime logs", "Identify cause"],
            },
            {
                "title": "Patch the affected files",
                "items": ["Make focused changes", "Preserve unrelated work", "Update UI/API flow"],
            },
            {
                "title": "Run targeted verification",
                "items": ["Compile/build changed parts", "Probe the live path", "Report remaining risk"],
            },
        ]
    if re.search(r"\b(search|research|find|compare|analyze|explain|summarize|report|sources|web)\b", lowered):
        if not re.search(r"\b(report|research plan|deep research|compare|analyze|sources|with citations|write|create|build|then|and)\b", lowered):
            return []
        return [
            {
                "title": "Understand the research question",
                "items": ["Identify the exact question", "List needed evidence", "Choose search scope"],
            },
            {
                "title": "Gather relevant information",
                "items": ["Search reliable sources", "Capture useful findings", "Track source links"],
            },
            {
                "title": "Synthesize the answer",
                "items": ["Compare findings", "Write the response", "Call out uncertainty"],
            },
            {
                "title": "Verify the final result",
                "items": ["Check dates and claims", "Confirm source coverage", "Report limitations"],
            },
        ]
    if re.search(r"\b(code|build|create|make|implement|add|app|website|ui|file|script|tool|refactor)\b", lowered):
        return [
            {
                "title": "Understand the requested deliverable",
                "items": ["Parse the goal", "Identify expected output", "Choose implementation path"],
            },
            {
                "title": "Inspect the relevant project context",
                "items": ["Read related files", "Reuse existing patterns", "Find integration points"],
            },
            {
                "title": "Implement the requested change",
                "items": ["Edit the needed files", "Keep artifacts visible", "Preserve unrelated work"],
            },
            {
                "title": "Run verification",
                "items": ["Build or compile", "Run targeted checks", "Surface remaining risk"],
            },
        ]
    return [
        {
            "title": "Analyze and plan request",
            "items": ["Identify core requirements", "Map dependencies and resources"],
        },
        {
            "title": "Execute the required steps",
            "items": ["Perform direct actions or content generation", "Inspect intermediate results"],
        },
        {
            "title": "Verify final result",
            "items": ["Perform sanity checks or verify syntax", "Ensure overall compliance"],
        },
    ]


def build_workflow_todo_items(prompt: str) -> List[str]:
    return [str(item.get("title", "")).strip() for item in build_workflow_plan(prompt) if str(item.get("title", "")).strip()]


def build_workflow_todo_markdown(prompt: str, plan: List[Dict[str, Any]]) -> str:
    lines = ["# TODO Plan", "", f"Task: {str(prompt or '').strip()}", ""]
    for index, item in enumerate(plan, start=1):
        title = str(item.get("title", "")).strip() or f"Phase {index}"
        lines.append(f"- [ ] Phase {index}: {title}")
        for child in item.get("items", []) or []:
            child_text = str(child).strip()
            if child_text:
                lines.append(f"  - [ ] {child_text}")
    return "\n".join(lines).strip() + "\n"


def write_workspace_todo_plan(content: str) -> str:
    """Persist the visible agent plan as a real workspace file."""
    workspace_dir = os.path.join(_ROOT, "workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    todo_path = os.path.abspath(os.path.join(workspace_dir, "todo.md"))
    if os.path.commonpath([os.path.abspath(workspace_dir), todo_path]) != os.path.abspath(workspace_dir):
        raise HTTPException(status_code=400, detail="Invalid todo path")
    temp_path = f"{todo_path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_path, todo_path)
    return os.path.relpath(todo_path, _ROOT)


def workflow_needs_plan(prompt: str) -> bool:
    # Disable automatic plan generation/auto-creation of phases by default
    return False


def clear_workspace_todo_plan() -> None:
    try:
        todo_path = os.path.abspath(os.path.join(_ROOT, "workspace", "todo.md"))
        if os.path.exists(todo_path):
            os.remove(todo_path)
    except Exception:
        pass


def prompt_requests_resume(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(word in text for word in [
        "continue",
        "resume",
        "carry on",
        "keep going",
        "go on",
        "finish it",
        "continue this",
        "resume task",
        "continue task",
    ])


def latest_todo_snapshot(session_id: str) -> Dict[str, Any]:
    path = work_events_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_events = [json.loads(line) for line in f if line.strip()]
            for event in reversed(raw_events):
                if not isinstance(event, dict):
                    continue
                role = str(event.get("role") or "").lower()
                target = str(event.get("target") or event.get("path") or "").lower()
                preview = str(event.get("preview") or "")
                if preview and (role == "planning_artifact" or target.endswith("todo.md")) and parse_todo_markdown(preview):
                    return {
                        "content": preview,
                        "turn_id": str(event.get("turn_id") or ""),
                        "task": str(event.get("task") or ""),
                    }
        except Exception:
            pass

    todo_path = os.path.abspath(os.path.join(_ROOT, "workspace", "todo.md"))
    if os.path.exists(todo_path):
        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                content = f.read()
            if parse_todo_markdown(content):
                return {"content": content, "turn_id": "", "task": ""}
        except Exception:
            pass
    return {}


def append_todo_events_from_content(
    session_id: str,
    content: str,
    turn_id: str,
    resumed_from_turn_id: str = "",
) -> None:
    plan = parse_todo_markdown(content)
    if not plan:
        return
    task_text = "Agent Workspace Plan"
    task_match = re.search(r"^\s*Task:\s*(.*)", content, re.IGNORECASE | re.MULTILINE)
    if task_match:
        task_text = task_match.group(1).strip() or task_text
    todo_rel_path = write_workspace_todo_plan(content)
    resume_meta = {}
    if resumed_from_turn_id:
        resume_meta = {
            "resumed": True,
            "resumed_from_turn_id": resumed_from_turn_id,
            "resume_label": "Continuing",
        }
    append_work_event(session_id, {
        "id": f"todo_file_{turn_id}",
        "kind": "file",
        "type": "file",
        "action": "Edit file",
        "title": "todo.md",
        "task": task_text,
        "target": todo_rel_path,
        "path": todo_rel_path,
        "preview": content,
        "status": "done",
        "turn_id": turn_id,
        "phase": f"Phase 1: {plan[0].get('title', 'Plan')}",
        "phase_index": 1,
        "role": "planning_artifact",
        **resume_meta,
    })
    for index, item in enumerate(plan, start=1):
        title = item.get("title", f"Phase {index}")
        items = item.get("items", [])
        checked = item.get("checked_items", [])
        append_work_event(session_id, {
            "id": f"todo_phase_{turn_id}_{index}",
            "kind": "todo",
            "type": "todo",
            "action": title,
            "title": title,
            "task": task_text,
            "target": title,
            "items": items,
            "checked_items": checked,
            "status": item.get("status", "running" if index == 1 else "pending"),
            "turn_id": turn_id,
            "phase": f"Phase {index}: {title}",
            "phase_index": index,
            **resume_meta,
        })


def start_chat_workflow(session_id: str, prompt: str, turn_id: str = "") -> str:
    # A todo.md plan belongs to the active turn. Clear stale plans before the
    # model/orchestrator decides whether this prompt actually needs phases.
    if prompt_requests_resume(prompt):
        snapshot = latest_todo_snapshot(session_id)
        content = str(snapshot.get("content") or "")
        if content:
            append_todo_events_from_content(
                session_id,
                content,
                turn_id,
                resumed_from_turn_id=str(snapshot.get("turn_id") or ""),
            )
            return content
    clear_workspace_todo_plan()
    return ""


def complete_chat_workflow(session_id: str, prompt: str, turn_id: str = "", status: str = "done") -> None:
    sid = safe_session_id(session_id)
    events = list_work_events(sid, limit=1000, active_turn_id=turn_id)
    if turn_id:
        events = [e for e in events if str(e.get("turn_id", "")) == turn_id]
    todo_events = [e for e in events if e.get("kind") == "todo" and e.get("phase_index") is not None]
    if not todo_events:
        return
    
    # Sort todo events by phase_index
    todo_events.sort(key=lambda x: int(x.get("phase_index") or 0))

    final_status = str(status or "done").lower()
    if final_status != "done":
        updated_events = []
        for e in todo_events:
            if str(e.get("status") or "").lower() in {"running", "working"}:
                e["status"] = final_status
                updated_events.append(e)
        for event in updated_events:
            append_work_event(sid, event)
        return
    
    updated_events = []
    for e in todo_events:
        items = e.get("items") or []
        e["checked_items"] = list(items)
        e["status"] = "done"
        updated_events.append(e)
        
    prompt_text = todo_events[0].get("task", "Agent Workspace Plan")
    lines = ["## TODO List", "", f"Task: {prompt_text}", ""]
    for e in todo_events:
        idx = e.get("phase_index")
        title = e.get("title")
        items = e.get("items") or []
        lines.append(f"- [x] Phase {idx}: {title}")
        for item in items:
            lines.append(f"  - [x] {item}")
            
    todo_content = "\n".join(lines).strip() + "\n"
    todo_rel_path = write_workspace_todo_plan(todo_content)
    
    todo_file_event = {
        "kind": "file",
        "type": "file",
        "action": "Edit file",
        "title": "todo.md",
        "task": prompt_text,
        "target": todo_rel_path,
        "path": todo_rel_path,
        "preview": todo_content,
        "status": "done",
        "turn_id": turn_id,
        "phase": f"Phase {len(todo_events)}: {todo_events[-1].get('title')}",
        "phase_index": len(todo_events),
        "role": "planning_artifact",
    }
    updated_events.append(todo_file_event)
    
    for event in updated_events:
        append_work_event(sid, event)


def list_work_events(session_id: str, limit: int = 200, active_turn_id: str = "") -> List[Dict[str, Any]]:
    path = work_events_path(session_id)
    raw_events: List[Dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            raw_events.append(event)
                    except Exception:
                        continue
        except Exception:
            pass

    # Keep persisted todo/planning events. They are the durable record that lets
    # an interrupted task display again later without inventing fake phases.
    filtered_events = []
    latest_turn_id = str(active_turn_id or "")
    for evt in raw_events:
        filtered_events.append(evt)
        if evt.get("turn_id"):
            latest_turn_id = str(evt.get("turn_id"))

    has_persisted_plan = any(
        evt.get("kind") == "todo" or evt.get("role") == "planning_artifact"
        for evt in filtered_events
    )

    # Fall back to workspace/todo.md only when the event log has no durable
    # planning events. Injecting this snapshot into an existing turn makes
    # Planning appear first even when the agent actually searched, read, or ran
    # a command first.
    todo_path = os.path.join(_ROOT, "workspace", "todo.md")
    if os.path.exists(todo_path) and not has_persisted_plan and not filtered_events:
        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                content = f.read()
            plan = parse_todo_markdown(content)
            task_text = "Agent Workspace Plan"
            task_match = re.search(r"^\s*Task:\s*(.*)", content, re.IGNORECASE | re.MULTILINE)
            if task_match:
                task_text = task_match.group(1).strip()
            
            todo_rel_path = os.path.relpath(todo_path, _ROOT)
            
            snapshot_time = os.path.getmtime(todo_path)
            file_event = {
                "id": f"todo_file_snapshot_{int(snapshot_time * 1000)}",
                "kind": "file",
                "type": "file",
                "action": "Edit file",
                "title": "todo.md",
                "task": task_text,
                "target": todo_rel_path,
                "path": todo_rel_path,
                "preview": content,
                "status": "done",
                "created_at": snapshot_time,
                "turn_id": latest_turn_id,
                "role": "planning_artifact",
            }
            if plan:
                file_event["phase"] = f"Phase 1: {plan[0].get('title', 'Plan')}"
                file_event["phase_index"] = 1
            filtered_events.append(file_event)
                
            if plan:
                # Add todo phase events
                for index, item in enumerate(plan, start=1):
                    title = item.get("title", f"Phase {index}")
                    items = item.get("items", [])
                    checked = item.get("checked_items", [])
                    status = "done" if len(checked) >= len(items) and len(items) > 0 else "running" if index == 1 else "pending"
                    
                    phase_event = {
                        "id": f"todo_phase_snapshot_{int(snapshot_time * 1000)}_{index}",
                        "kind": "todo",
                        "type": "todo",
                        "action": title,
                        "title": title,
                        "task": task_text,
                        "target": title,
                        "items": items,
                        "checked_items": checked,
                        "status": item.get("status", status),
                        "created_at": snapshot_time + (index * 0.001),
                        "turn_id": latest_turn_id,
                        "phase": f"Phase {index}: {title}",
                        "phase_index": index,
                    }
                    filtered_events.append(phase_event)
        except Exception as e:
            print(f"[API_ERROR]: Failed to dynamically parse todo.md: {e}")

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for event in filtered_events:
        key = (
            str(event.get("turn_id", "")),
            str(event.get("kind") or event.get("type") or ""),
            str(event.get("role") or ""),
            str(event.get("phase_index") or ""),
            str(event.get("path") or event.get("target") or event.get("command") or event.get("title") or ""),
        )
        event_id = str(event.get("id") or "")
        dedupe_key = event_id or "|".join(key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(event)

    return deduped[-max(1, min(limit, 1000)):]


def attach_work_events_to_chunk(session_id: str, chunk: str, turn_id: str = "") -> str:
    _THREAD_LOCAL.appended_events = []
    next_lines = []
    for line in str(chunk or "").splitlines(keepends=True):
        activity = re.match(r"^(\s*)\[NEXUS_ACTIVITY\]:\s*(\{.*\})(\s*)$", line.rstrip("\r\n"), re.IGNORECASE)
        if not activity:
            next_lines.append(line)
            continue
        try:
            payload = json.loads(activity.group(2))
            if turn_id:
                payload.setdefault("turn_id", turn_id)
            event = append_work_event(session_id, payload)
            newline = "\n" if line.endswith("\n") else ""
            next_lines.append(f"{activity.group(1)}[NEXUS_ACTIVITY]: {json.dumps(event, ensure_ascii=False)}{newline}")
        except Exception:
            next_lines.append(line)
            
    extra_events = []
    if hasattr(_THREAD_LOCAL, "appended_events"):
        line_event_ids = {e.get("id") for e in _THREAD_LOCAL.appended_events if e.get("id") and any(e.get("id") in l for l in next_lines)}
        for evt in _THREAD_LOCAL.appended_events:
            if evt.get("id") not in line_event_ids:
                extra_events.append(evt)
                
    for evt in extra_events:
        next_lines.append(f"[NEXUS_ACTIVITY]: {json.dumps(evt, ensure_ascii=False)}\n")
        
    return "".join(next_lines)


def filter_chat_chunk(chunk: str, show_thinking: bool = False) -> str:
    """Hide internal stream status markers and ANSI codes from user-facing chat."""
    if show_thinking:
        return chunk
    # 1. Strip all ANSI escape codes globally
    cleaned = re.sub(r"\033\[[0-9;]*m", "", str(chunk or ""))
    filtered = []
    for line in cleaned.splitlines(keepends=True):
        text = line.strip()
        if not text:
            filtered.append(line)
            continue
        if text in {"[STARTING]", "[STARTING...]", "[ABORTED]"}:
            continue
        if re.match(r"^\[THINKING(?::[^\]]*)?]$", text, re.IGNORECASE):
            continue
        if re.match(r"^\[NEXUS_BOOT\]:", text, re.IGNORECASE):
            continue
        if re.match(r"^\[HIVE[:\s]", text, re.IGNORECASE):
            continue
        if re.match(r"^\[(SYSTEM|ERROR|PROVIDER_ERROR|LAW_BLOCKED|PERMISSION_DENIED|NEXUS_SYSTEM_ERROR)[:\]]", text, re.IGNORECASE):
            continue
        if re.match(r"^\[THINKING: TURN \d+\]$", text, re.IGNORECASE):
            continue
        if re.match(r"^\[AUTO_OBSERVATION\]:", text, re.IGNORECASE):
            continue
        if re.match(r"^\[(ADVISORY|SUCCESS|EVOLUTION)\]:", text, re.IGNORECASE):
            continue
        # Skip lines that are purely ANSI remnants or empty brackets
        if re.match(r"^\[.*\]$", text) and len(text) < 60 and not any(c.isalpha() for c in text.strip("[]")):
            continue
        filtered.append(line)
    return "".join(filtered)

def get_loop(session_id: str = "default") -> NexusLoop:
    from session_bus import sync_loop_from_disk

    session_id = safe_session_id(session_id)
    if session_id not in _LOOPS:
        loop = NexusLoop(root_dir=_ROOT)
        loop.load_memory(session_id)
        _LOOPS[session_id] = loop
    else:
        sync_loop_from_disk(_LOOPS[session_id])
    return _LOOPS[session_id]

@app.get("/api/sessions/active")
def get_active_session():
    from session_bus import get_active_session, load_session_history

    active = get_active_session(_ROOT)
    sid = safe_session_id(active.get("session_id", "default"))
    loop = get_loop(sid)
    return {
        "session_id": sid,
        "source": active.get("source", "unknown"),
        "updated_at": active.get("updated_at", 0),
        "history": loop.memory,
    }

@app.post("/api/sessions/active")
async def set_active_session(request: Request):
    from session_bus import set_active_session_id

    data = await request.json()
    sid = set_active_session_id(_ROOT, data.get("session_id", "default"), source=str(data.get("source", "api")))
    loop = get_loop(sid)
    return {"status": "success", "session_id": sid, "history": loop.memory}

@app.get("/api/sessions")
def list_sessions():
    sessions_dir = os.path.join(_ROOT, "logs", "sessions")
    if not os.path.exists(sessions_dir):
        os.makedirs(sessions_dir, exist_ok=True)
    
    files = [f for f in os.listdir(sessions_dir) if f.endswith(".json")]
    results = []
    for f in files:
        path = os.path.join(sessions_dir, f)
        mtime = os.path.getmtime(path)
        sid = f.replace(".json", "")
        # Try to get a preview/title
        meta_path = os.path.join(sessions_dir, f"{sid}.meta")
        title = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding='utf-8') as mf:
                    meta = json.load(mf)
                    title = meta.get("title")
            except Exception as e:
                print(f"[API_ERROR]: Failed to read session meta for {sid}: {e}")
            
        if not title:
            try:
                with open(path, "r", encoding='utf-8') as sf:
                    data = json.load(sf)
                    title = data[0]["content"][:50] if data and len(data) > 0 else "New Chat"
            except:
                title = "Untitled Session"
            
        results.append({
            "id": sid,
            "title": title,
            "updated_at": mtime
        })
    
    # Sort by mtime descending
    results.sort(key=lambda x: x["updated_at"], reverse=True)
    return results

@app.post("/api/sessions/new")
def create_session():
    from session_bus import set_active_session_id

    new_id = f"session_{int(time.time())}"
    clear_workspace_todo_plan()
    loop = get_loop(new_id)
    loop.save_memory()
    set_active_session_id(_ROOT, new_id, source="gui")
    return {"id": new_id, "title": "New Chat"}

@app.post("/api/sessions/load")
async def load_session(request: Request):
    from session_bus import set_active_session_id

    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    set_active_session_id(_ROOT, sid, source=str(data.get("source", "gui")))
    loop = get_loop(sid)
    return {"status": "success", "id": loop.session_id, "history": loop.memory}

def _clear_session_files(session_id: str) -> bool:
    """Reset or remove persisted session data and in-memory loop cache."""
    path = session_file_path(session_id)
    meta_path = session_file_path(session_id, ".meta")
    existed = os.path.exists(path) or os.path.exists(meta_path) or session_id in _LOOPS

    clear_workspace_todo_plan()

    with open(path, "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"title": "New Chat"}, f)

    if session_id in _LOOPS:
        loop = _LOOPS[session_id]
        loop.memory = []
        try:
            loop.save_memory()
        except Exception:
            pass

    return existed


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    session_id = safe_session_id(session_id)

    if session_id == "default":
        if not _clear_session_files(session_id):
            raise HTTPException(status_code=404, detail="Default session not found")
        return {
            "status": "success",
            "id": session_id,
            "deleted": False,
            "cleared": True,
            "message": "Default session cleared",
        }

    path = session_file_path(session_id)
    meta_path = session_file_path(session_id, ".meta")
    if not os.path.exists(path) and session_id not in _LOOPS:
        return {"status": "error", "id": session_id, "deleted": False, "message": "Session not found"}

    if os.path.exists(path):
        os.remove(path)
    if os.path.exists(meta_path):
        os.remove(meta_path)
    if session_id in _LOOPS:
        del _LOOPS[session_id]
    return {"status": "success", "id": session_id, "deleted": True}

@app.post("/api/sessions/rename")
async def rename_session(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    new_title = str(data.get("title", "")).strip()[:120]
    path = session_file_path(sid)
    if os.path.exists(path):
        meta_path = session_file_path(sid, ".meta")
        with open(meta_path, "w", encoding='utf-8') as f:
            json.dump({"title": new_title}, f)
        return {"status": "success"}
    return {"status": "error"}

@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Invalid chat JSON: {exc}"},
            status_code=400,
        )
    from session_bus import set_active_session_id

    prompt = str(data.get("prompt", ""))[:50000]
    sid = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    set_active_session_id(_ROOT, sid, source=str(data.get("source", "gui")))
    loop = get_loop(sid)
    loop.reset()
    
    # Normalize provider
    from kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    default_p = kernel.config.get_system("provider_name", "openrouter")
    raw_provider = data.get("provider") or default_p
    provider = str(raw_provider).lower().replace(" ", "_")
    show_thinking = bool(data.get("show_thinking", _SHOW_CHAT_THINKING))
    
    # Auto-title session if new
    meta_path = session_file_path(sid, ".meta")
    should_write = False
    if not os.path.exists(meta_path):
        should_write = True
    else:
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                if meta.get("title") == "New Chat":
                    should_write = True
        except:
            should_write = True

    if should_write:
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"title": prompt[:50]}, f)
        except Exception as e:
            print(f"[API_ERROR]: Failed to write session meta: {e}")

    resume_todo_context = ""
    try:
        resume_todo_context = await asyncio.to_thread(start_chat_workflow, sid, prompt, turn_id)
    except Exception as e:
        print(f"[API_ERROR]: Failed to start chat workflow events: {e}")

    effective_prompt = prompt
    if resume_todo_context:
        effective_prompt = (
            f"{prompt}\n\n"
            "[NEXUS_RESUME_CONTEXT]\n"
            "Continue the saved task below instead of restarting from scratch. "
            "Use the unfinished phases/items as the real work plan, update todo.md as work progresses, "
            "and emit only real work activity events for actual files, commands, tools, searches, or browser actions.\n\n"
            f"{resume_todo_context}\n"
            "[/NEXUS_RESUME_CONTEXT]"
        )

    async def event_generator():
        completed = False
        partial_response = []
        idle_timeout = max(5, int(os.environ.get("NEXUS_CHAT_IDLE_TIMEOUT", "90")))
        stream_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        def run_loop_stream() -> None:
            try:
                for stream_chunk in loop.stream_run(effective_prompt, provider=provider):
                    stream_queue.put(("chunk", stream_chunk))
                stream_queue.put(("done", ""))
            except Exception as stream_error:
                stream_queue.put(("error", str(stream_error)))

        threading.Thread(target=run_loop_stream, daemon=True).start()

        try:
            while True:
                try:
                    kind, chunk = await asyncio.to_thread(stream_queue.get, True, idle_timeout)
                except queue.Empty:
                    chunk = (
                        "\nNEXUS chat timed out while waiting for the model/provider. "
                        "Check provider configuration or switch to a healthy local model."
                    )
                    partial_response.append(chunk)
                    try:
                        loop.abort()
                    except Exception:
                        pass
                    yield chunk
                    break

                if kind == "done":
                    completed = True
                    break
                if kind == "error":
                    raise RuntimeError(chunk)

                partial_response.append(chunk)
                visible_chunk = filter_chat_chunk(chunk, show_thinking=show_thinking)
                visible_chunk = attach_work_events_to_chunk(sid, visible_chunk, turn_id=turn_id)
                if visible_chunk:
                    yield visible_chunk
        except Exception as e:
            print(f"[CHAT_ERROR]: {e}")
            error_text = f"\nNEXUS chat error: {str(e)}"
            partial_response.append(error_text)
            try:
                complete_chat_workflow(sid, prompt, turn_id=turn_id, status="error")
            except Exception:
                pass
            yield error_text
        finally:
            if completed:
                try:
                    complete_chat_workflow(sid, prompt, turn_id=turn_id, status="done")
                except Exception as e:
                    print(f"[API_ERROR]: Failed to complete chat workflow: {e}")
            else:
                try:
                    existing = loop.memory[-2:] if len(loop.memory) >= 2 else []
                    already_saved = (
                        len(existing) == 2
                        and existing[0].get("role") == "user"
                        and existing[0].get("content") == prompt
                    )
                    if not already_saved:
                        loop.memory.append({"role": "user", "content": prompt})
                        assistant_text = "".join(partial_response).strip()
                        if assistant_text:
                            loop.memory.append({"role": "assistant", "content": assistant_text})
                        loop.save_memory()
                except Exception as save_error:
                    print(f"[API_ERROR]: Failed to save interrupted chat stream: {save_error}")
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    saved_paths = []
    source_items = []
    for file in files:
        file_path = safe_upload_path(file.filename)
        total = 0
        with open(file_path, "wb") as buffer:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    buffer.close()
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    raise HTTPException(status_code=413, detail="Upload too large")
                buffer.write(chunk)
        saved_paths.append(file_path)
        rel_path = os.path.relpath(file_path, _ROOT).replace("\\", "/")
        source_items.append(upsert_source_library({
            "id": f"file_{uuid.uuid4().hex[:10]}",
            "name": os.path.basename(file_path),
            "type": "File",
            "path": rel_path,
            "checked": True,
        }))
        try:
            get_loop("default").rag.index_workspace(file_path=rel_path)
        except Exception as index_error:
            print(f"[SOURCE_WARN]: Could not index upload {rel_path}: {index_error}")
    
    # Notify brain_loop about new files if needed
    # brain_loop.inject_system_message(f"[SYSTEM]: User uploaded {len(saved_paths)} files to workspace/uploads.")
    
    return {"status": "success", "files": saved_paths, "sources": source_items}


@app.get("/api/sources")
def get_sources():
    return {"sources": load_source_library()}


@app.post("/api/sources/website")
async def import_website_source(request: Request):
    data = await request.json()
    raw_url = str(data.get("url") or "").strip()
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Enter a valid http(s) URL")

    try:
        req = urllib.request.Request(raw_url, headers={"User-Agent": "NEXUS-AI-Source-Importer/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(_MAX_UPLOAD_BYTES + 1)
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Website source is too large")
        text = raw.decode("utf-8", errors="replace")
        if "html" in content_type.lower() or "<html" in text[:2000].lower():
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                title = soup.title.get_text(" ", strip=True) if soup.title else parsed.netloc
                body = soup.get_text("\n", strip=True)
                text = f"# {title}\n\nSource URL: {raw_url}\n\n{body}"
            except Exception:
                title = parsed.netloc
                text = f"Source URL: {raw_url}\n\n{text}"
        else:
            title = os.path.basename(parsed.path.strip("/")) or parsed.netloc
            text = f"Source URL: {raw_url}\nContent-Type: {content_type}\n\n{text}"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import website: {exc}")

    safe_host = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed.netloc).strip("._") or "website"
    file_name = f"web_{safe_host}_{uuid.uuid4().hex[:8]}.txt"
    file_path = safe_upload_path(file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text[:_MAX_UPLOAD_BYTES])
    rel_path = os.path.relpath(file_path, _ROOT).replace("\\", "/")
    source = upsert_source_library({
        "id": f"web_{uuid.uuid4().hex[:10]}",
        "name": str(data.get("name") or title or parsed.netloc)[:180],
        "type": "Website",
        "path": rel_path,
        "url": raw_url,
        "checked": True,
    })
    try:
        get_loop("default").rag.index_workspace(file_path=rel_path)
    except Exception as index_error:
        print(f"[SOURCE_WARN]: Could not index website {rel_path}: {index_error}")
    return {"status": "success", "source": source}


@app.patch("/api/sources/{source_id}")
async def patch_source(source_id: str, request: Request):
    data = await request.json()
    return {"status": "success", "source": update_source_library(source_id, data)}


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str):
    delete_source_library(source_id)
    return {"status": "success"}

@app.get("/api/history")
def get_history(session_id: str = "default"):
    loop = get_loop(session_id)
    loop.sync_memory()
    return loop.memory


@app.get("/api/work-events")
def get_work_events(session_id: str = "default", limit: int = 200, turn_id: str = ""):
    events = list_work_events(session_id, limit=limit, active_turn_id=turn_id)
    if turn_id:
        events = [
            event for event in events
            if str(event.get("turn_id", "")) == turn_id
        ]
    return {"events": events}


@app.get("/api/work-events/{event_id}")
def get_work_event(event_id: str, session_id: str = "default"):
    for event in reversed(list_work_events(session_id, limit=1000)):
        if str(event.get("id")) == event_id:
            return event
    raise HTTPException(status_code=404, detail="Work event not found")


@app.post("/api/work-events/update")
async def update_work_event(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    operation = str(data.get("operation") or "update").lower().strip()
    title = str(data.get("title") or data.get("action") or "Workflow update").strip()[:180]
    target = str(data.get("target") or title).strip()[:4000]
    status = str(data.get("status") or ("deleted" if operation == "delete" else "running")).lower().strip()
    raw_items = data.get("items", [])
    items = [str(item).strip() for item in raw_items if str(item).strip()] if isinstance(raw_items, list) else []
    event_id = str(data.get("event_id") or data.get("id") or "").strip()
    payload = {
        "kind": str(data.get("kind") or "todo"),
        "type": str(data.get("type") or "todo"),
        "action": title,
        "title": title,
        "target": target,
        "items": items,
        "status": status,
        "operation": operation,
        "turn_id": turn_id,
        "parent_id": str(data.get("parent_id") or ""),
    }
    if data.get("phase"):
        payload["phase"] = str(data.get("phase"))[:180]
    if data.get("phase_index") is not None:
        payload["phase_index"] = data.get("phase_index")
    if event_id:
        payload["id"] = event_id
    event = append_work_event(sid, payload)
    return {"status": "success", "event": event}


@app.post("/api/work-events/run-command")
async def run_work_command(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    command = str(data.get("command") or data.get("target") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")
    if len(command) > 4000:
        raise HTTPException(status_code=413, detail="Command is too large")

    timeout_raw = data.get("timeout", 90)
    try:
        timeout = max(5, min(int(timeout_raw), 180))
    except Exception:
        timeout = 90

    from tools.nexus_tools.bash_tool import BashTool

    parent_event = None
    parent_event_id = str(data.get("event_id") or "").strip()
    if parent_event_id:
        for existing in reversed(list_work_events(sid, limit=1000)):
            if str(existing.get("id")) == parent_event_id:
                parent_event = existing
                break
    started_payload = {
        "kind": "command",
        "type": "command",
        "action": "Run command",
        "title": "Run command",
        "target": command,
        "command": command,
        "status": "running",
        "turn_id": turn_id,
        "parent_id": parent_event_id,
    }
    if parent_event and parent_event.get("phase"):
        started_payload["phase"] = parent_event.get("phase")
    if parent_event and parent_event.get("phase_index") is not None:
        started_payload["phase_index"] = parent_event.get("phase_index")
    started = append_work_event(sid, started_payload)
    result = BashTool(_ROOT).call(command=command, timeout=timeout)
    stdout = str(result.data or "")
    stderr = str(result.error or "")
    status = "error" if result.error else "done"
    completed = append_work_event(sid, {
        **started,
        "id": f"{started.get('id')}_result",
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "output": "\n".join(part for part in [stdout, stderr] if part).strip(),
        "result": stderr or stdout or "",
        "completed_at": time.time(),
    })
    return {"status": status, "event": completed, "stdout": stdout, "stderr": stderr, "output": completed.get("output", ""), "command": command}


@app.post("/api/work-events/run-command-stream")
async def run_work_command_stream(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    command = str(data.get("command") or data.get("target") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")
    if len(command) > 4000:
        raise HTTPException(status_code=413, detail="Command is too large")

    try:
        timeout = max(5, min(int(data.get("timeout", 90)), 180))
    except Exception:
        timeout = 90

    parent_event = None
    parent_event_id = str(data.get("event_id") or "").strip()
    if parent_event_id:
        for existing in reversed(list_work_events(sid, limit=1000)):
            if str(existing.get("id")) == parent_event_id:
                parent_event = existing
                break

    started_payload = {
        "kind": "command",
        "type": "command",
        "action": "Run command",
        "title": "Run command",
        "target": command,
        "command": command,
        "status": "running",
        "turn_id": turn_id,
        "parent_id": parent_event_id,
    }
    if parent_event and parent_event.get("phase"):
        started_payload["phase"] = parent_event.get("phase")
    if parent_event and parent_event.get("phase_index") is not None:
        started_payload["phase_index"] = parent_event.get("phase_index")
    started = append_work_event(sid, started_payload)

    async def event_stream():
        output_parts: List[str] = []
        chunks_list: List[List[Any]] = []
        started_time = time.time()

        def sse(payload: Dict[str, Any]) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield sse({"type": "start", "event": started, "command": command})
        try:
            from tools.nexus_tools.bash_tool import BashTool
            tool = BashTool(_ROOT)
            assessment = tool.risk_scorer.assess(command)
            if os.environ.get("NEXUS_ALLOW_DANGEROUS_SHELL", "false").lower() != "true" and assessment.blocked:
                blocked = f"Command blocked by risk policy: {assessment.summary()}"
                chunks_list.append([time.time() - started_time, blocked])
                completed = append_work_event(sid, {
                    **started,
                    "id": f"{started.get('id')}_result",
                    "status": "error",
                    "stdout": "",
                    "stderr": blocked,
                    "output": blocked,
                    "result": blocked,
                    "completed_at": time.time(),
                    "chunks": chunks_list,
                })
                yield sse({"type": "chunk", "stream": "stderr", "text": blocked})
                yield sse({"type": "done", "status": "error", "event": completed, "stdout": "", "stderr": blocked, "output": blocked})
                return

            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            deadline = time.time() + timeout
            assert proc.stdout is not None
            while True:
                remaining = max(0.1, deadline - time.time())
                try:
                    chunk = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    text = f"Command timed out after {timeout}s"
                    output_parts.append(text)
                    chunks_list.append([time.time() - started_time, text])
                    completed = append_work_event(sid, {
                        **started,
                        "id": f"{started.get('id')}_result",
                        "status": "error",
                        "stdout": "".join(output_parts),
                        "stderr": text,
                        "output": "".join(output_parts),
                        "result": text,
                        "completed_at": time.time(),
                        "chunks": chunks_list,
                    })
                    yield sse({"type": "chunk", "stream": "stderr", "text": text})
                    yield sse({"type": "done", "status": "error", "event": completed, "stdout": "".join(output_parts), "stderr": text, "output": "".join(output_parts)})
                    return
                if not chunk:
                    break
                text = chunk.decode(errors="replace")
                output_parts.append(text)
                chunks_list.append([time.time() - started_time, text])
                yield sse({"type": "chunk", "stream": "stdout", "text": text})

            return_code = await proc.wait()
            output = "".join(output_parts)
            status = "done" if return_code == 0 else "error"
            completed = append_work_event(sid, {
                **started,
                "id": f"{started.get('id')}_result",
                "status": status,
                "stdout": output,
                "stderr": "",
                "output": output,
                "result": output,
                "exit_code": return_code,
                "completed_at": time.time(),
                "chunks": chunks_list,
            })
            yield sse({"type": "done", "status": status, "event": completed, "stdout": output, "stderr": completed.get("stderr", ""), "output": output, "exit_code": return_code})
        except Exception as exc:
            text = str(exc)
            chunks_list.append([time.time() - started_time, text])
            completed = append_work_event(sid, {
                **started,
                "id": f"{started.get('id')}_result",
                "status": "error",
                "stdout": "".join(output_parts),
                "stderr": text,
                "output": "".join(output_parts) or text,
                "result": text,
                "completed_at": time.time(),
                "chunks": chunks_list,
            })
            yield sse({"type": "chunk", "stream": "stderr", "text": text})
            yield sse({"type": "done", "status": "error", "event": completed, "stdout": "".join(output_parts), "stderr": text, "output": "".join(output_parts) or text})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/file-preview")
def file_preview(path: str):
    file_path = safe_workspace_read_path(path)
    rel = os.path.relpath(file_path, _ROOT)
    _, ext = os.path.splitext(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read(250000)
    return {
        "path": rel,
        "name": os.path.basename(file_path),
        "ext": ext.lstrip(".") or "txt",
        "content": content,
        "truncated": os.path.getsize(file_path) > len(content.encode("utf-8", errors="ignore")),
    }


@app.get("/api/file-download")
def file_download(path: str):
    file_path = safe_workspace_read_path(path)
    return FileResponse(file_path, filename=os.path.basename(file_path))


@app.get("/api/session-files.zip")
def session_files_zip(session_id: str = "default"):
    sid = safe_session_id(session_id)
    candidates: Dict[str, str] = {}

    for source in load_source_library():
        raw_path = str(source.get("path") or "").strip()
        if not raw_path:
            continue
        try:
            file_path = safe_workspace_read_path(raw_path)
            candidates[os.path.basename(file_path)] = file_path
        except HTTPException:
            pass

    artifact_dir = os.path.abspath(os.path.join(_ARTIFACTS_DIR, sid))
    artifact_root = os.path.abspath(_ARTIFACTS_DIR)
    if os.path.isdir(artifact_dir) and os.path.commonpath([artifact_root, artifact_dir]) == artifact_root:
        for name in os.listdir(artifact_dir):
            path = os.path.abspath(os.path.join(artifact_dir, name))
            if os.path.isfile(path) and os.path.commonpath([artifact_dir, path]) == artifact_dir:
                candidates[f"artifacts/{name}"] = path

    work_path = work_events_path(sid)
    if os.path.exists(work_path):
        try:
            with open(work_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    raw_path = str(event.get("path") or event.get("target") or "").strip()
                    if not raw_path:
                        continue
                    try:
                        file_path = safe_workspace_read_path(raw_path)
                        candidates[f"work/{os.path.basename(file_path)}"] = file_path
                    except HTTPException:
                        pass
        except OSError:
            pass

    if not candidates:
        raise HTTPException(status_code=404, detail="No downloadable files found for this chat")

    buffer = BytesIO()
    used_names = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, path in candidates.items():
            safe_name = re.sub(r"[^A-Za-z0-9_. /-]", "_", arcname).strip(" ./") or os.path.basename(path)
            base, ext = os.path.splitext(safe_name)
            unique_name = safe_name
            index = 2
            while unique_name in used_names:
                unique_name = f"{base}-{index}{ext}"
                index += 1
            used_names.add(unique_name)
            archive.write(path, unique_name)
    buffer.seek(0)
    filename = f"{sid}-files.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/screenshot/live")
def get_live_screenshot(timestamp: float = None):
    screenshot_dir = os.path.join(_ROOT, "workspace", "browser")
    if not os.path.exists(screenshot_dir):
        raise HTTPException(status_code=404, detail="No screenshots directory found")
    png_files = [
        os.path.join(screenshot_dir, f)
        for f in os.listdir(screenshot_dir)
        if f.lower().endswith(".png")
    ]
    if not png_files:
        raise HTTPException(status_code=404, detail="No screenshots found")
    
    if timestamp is not None:
        # Find the screenshot whose mtime is closest to and <= timestamp
        past_files = [f for f in png_files if os.path.getmtime(f) <= timestamp]
        if past_files:
            target_screenshot = max(past_files, key=os.path.getmtime)
        else:
            # Fallback to the oldest screenshot if none are <= timestamp
            target_screenshot = min(png_files, key=os.path.getmtime)
    else:
        target_screenshot = max(png_files, key=os.path.getmtime)
        
    return FileResponse(target_screenshot)



@app.post("/api/artifacts")
async def create_artifact(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    content = str(data.get("content", ""))
    if not content.strip():
        raise HTTPException(status_code=400, detail="Artifact content is required")
    if len(content.encode("utf-8", errors="ignore")) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Artifact is too large")

    lang = str(data.get("lang", "txt")).lower().strip() or "txt"
    name = safe_artifact_name(str(data.get("name", "")), lang)
    session_dir = os.path.abspath(os.path.join(_ARTIFACTS_DIR, sid))
    os.makedirs(session_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(session_dir, name))
    if os.path.commonpath([os.path.abspath(_ARTIFACTS_DIR), path]) != os.path.abspath(_ARTIFACTS_DIR):
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    with open(path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(content)

    rel = os.path.relpath(path, _ROOT)
    event_payload = {
        "kind": "file",
        "type": "file",
        "action": "Create file",
        "title": str(data.get("title") or f"Create {name}")[:160],
        "target": rel,
        "path": rel,
        "status": "done",
        "result": f"Saved {rel}",
        "lang": lang,
        "source": str(data.get("source", "assistant"))[:80],
        "turn_id": turn_id,
    }
    if data.get("phase"):
        event_payload["phase"] = str(data.get("phase"))[:180]
    if data.get("phase_index") is not None:
        event_payload["phase_index"] = data.get("phase_index")
    event = append_work_event(sid, event_payload)
    verify_event = None
    if name.lower().endswith(".py") or lang in {"python", "py"}:
        verify_payload = {
            "kind": "command",
            "type": "command",
            "action": "Run command",
            "title": f"Verify {name}",
            "target": f'python -m py_compile "{rel}"',
            "command": f'python -m py_compile "{rel}"',
            "status": "ready",
            "turn_id": turn_id,
        }
        if data.get("verify_phase"):
            verify_payload["phase"] = str(data.get("verify_phase"))[:180]
        if data.get("verify_phase_index") is not None:
            verify_payload["phase_index"] = data.get("verify_phase_index")
        verify_event = append_work_event(sid, verify_payload)
    return {"status": "success", "artifact": {"path": rel, "name": name, "lang": lang}, "event": event, "verify_event": verify_event}

# 🛡️ [STATE_CACHE]
_CACHE = {
    "state": None,
    "last_update": 0,
    "tools": None,
    "tools_last_update": 0,
    "skills": None,
    "skills_last_update": 0,
    "mcp": None,
    "mcp_last_update": 0,
    "providers": None,
    "providers_last_update": 0,
    "audit": None,
    "audit_last_update": 0,
}
_STATE_LOCK = threading.Lock()
_STATE_TTL_SECONDS = float(os.environ.get("NEXUS_DASHBOARD_STATE_TTL", "10"))
_METADATA_TTL_SECONDS = float(os.environ.get("NEXUS_DASHBOARD_METADATA_TTL", "120"))
_AUDIT_LOCK = threading.Lock()
_AUDIT_THREAD_ACTIVE = False

def _background_audit_build():
    global _AUDIT_THREAD_ACTIVE
    try:
        new_audit = build_audit_state()
        with _AUDIT_LOCK:
            _CACHE["audit"] = new_audit
            _CACHE["audit_last_update"] = time.time()
    finally:
        _AUDIT_THREAD_ACTIVE = False

def get_async_audit_state():
    global _AUDIT_THREAD_ACTIVE
    now = time.time()
    
    # Trigger background update if stale (every 30s)
    if not _AUDIT_THREAD_ACTIVE and (now - _CACHE["audit_last_update"]) > 30.0:
        _AUDIT_THREAD_ACTIVE = True
        threading.Thread(target=_background_audit_build, daemon=True).start()
        
    return _CACHE["audit"] or {
        "unified_graph": {"nodes": 0, "edges": 0},
        "roadmap": {"total": 0, "counts": {}, "completion_ratio": 0, "remaining_top": []},
        "evidence": {"total": 0, "by_status": {}},
        "mission_replay": [],
        "tool_economy": [],
    }


def _cache_fresh(key: str, ttl: float) -> bool:
    return _CACHE.get(key) is not None and (time.time() - float(_CACHE.get(f"{key}_last_update", 0) or 0)) < ttl


def _cached_component(key: str, ttl: float, builder, default):
    if _cache_fresh(key, ttl):
        return _CACHE[key]
    try:
        value = builder()
        _CACHE[key] = value
        _CACHE[f"{key}_last_update"] = time.time()
        return value
    except Exception as exc:
        print(f"[API_WARN] {key} refresh failed (using cached/default): {exc}")
        return _CACHE.get(key) if _CACHE.get(key) is not None else default


# CORS already configured above.



def clean_description(content):
    if not content: return None
    
    # 1. Improved YAML Frontmatter Extraction
    fm = re.search(r'^---\s*[\r\n]+(.*?)\n---', content, re.DOTALL | re.MULTILINE)
    if fm:
        meta_content = fm.group(1)
        d_match = re.search(r'description:\s*(.*)', meta_content, re.IGNORECASE)
        if d_match:
            return d_match.group(1).strip()[:150]
            
    # Remove frontmatter for further searching
    content = re.sub(r'^---.*?---', '', content, flags=re.DOTALL).strip()
    
    # 2. Extract first Header content or paragraph
    header_match = re.search(r'^#+\s+.*?\n+(.+)', content)
    if header_match:
        return header_match.group(1).strip().split('\n')[0][:120]
        
    # 3. First non-empty paragraph
    paras = [p.strip() for p in content.split('\n\n') if p.strip()]
    if paras:
        return paras[0].split('\n')[0][:120]
        
    return None

def extract_docstring(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(3000)
            match = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if not match: match = re.search(r"'''(.*?)'''", content, re.DOTALL)
            if match:
                return match.group(1).strip().split('\n')[0][:120]
    except Exception as e:
        print(f"[API_ERROR]: Failed to extract docstring from {file_path}: {e}")
    return None

def scan_metadata(directory, default_desc="Core NEXUS Capability"):
    """Scans a directory for subfolders and extracts metadata with docstring fallback."""
    results = []
    if not os.path.exists(directory):
        return results
    
    meta_files = ["SKILL.md", "README.md", "DESCRIPTION.md", "DESCRIPTION.txt", "INFO.md", "index.md"]

    for item in os.listdir(directory):
        path = os.path.join(directory, item)
        if os.path.isdir(path) and not item.startswith("__"):
            desc = None
            
            # Level 1 scan (Markdown)
            # Level 1-2: Markdown & JSON Meta Scan
            for meta_file in ["SKILL.md", "README.md", "DESCRIPTION.md", "metadata.json", "info.json"]:
                meta_path = os.path.join(path, meta_file)
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding='utf-8') as f:
                        meta_raw = f.read(3000)
                    if meta_file.endswith('.json'):
                        try:
                            j = json.loads(meta_raw)
                            desc = j.get('description', j.get('summary', ''))
                        except Exception as e:
                            print(f"[API_ERROR]: Failed to parse JSON meta in {path}: {e}")
                    else:
                        desc = clean_description(meta_raw)
                    if desc: break
            
            # Level 3: Recursive Deep-Scan
            if not desc:
                try:
                    for sub in os.listdir(path):
                        sub_path = os.path.join(path, sub)
                        if os.path.isdir(sub_path):
                            for m in ["SKILL.md", "README.md", "DESCRIPTION.md"]:
                                target = os.path.join(sub_path, m)
                                if os.path.exists(target):
                                    with open(target, "r", encoding='utf-8') as f:
                                        desc = clean_description(f.read(2000))
                                    if desc: break
                        if desc: break
                except Exception as e:
                    print(f"[API_ERROR]: Recursive scan failed for {path}: {e}")

            # Level 3 scan (Docstring Fallback)
            if not desc:
                for py_file in ["script.py", f"{item}.py", "tool.py", "__init__.py"]:
                    py_path = os.path.join(path, py_file)
                    desc = extract_docstring(py_path)
                    if desc: break
                if not desc:
                    # Final try: find any .py file if folder is small
                    try:
                        files = os.listdir(path)
                        for f in files:
                            if f.endswith(".py") and f not in ["__init__.py"]:
                                desc = extract_docstring(os.path.join(path, f))
                                if desc: break
                    except Exception as e:
                        print(f"[API_ERROR]: Final py-file scan failed for {path}: {e}")

            # Level 4: Technical Name-Based Heuristic (Prevent blank cards)
            if not desc:
                h_name = item.replace('_', ' ').replace('-', ' ').title()
                desc = f"Operational enclave node for {h_name} system integration."

            results.append({"name": item, "description": desc if desc else ""})
    return results


def _read_hive_manifest() -> Dict[str, Any]:
    manifest = os.path.join(_ROOT, "logs", "hive", "hive_manifest.json")
    if not os.path.exists(manifest):
        return {}
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[API_ERROR]: Failed to load hive manifest: {e}")
        return {}


def _hive_manifest_insights(hive_id: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Derive merge conflicts and weak artifacts for one hive from persisted manifest data."""
    from hive.engine import NexusHiveEngine

    tasks = manifest.get("tasks", [])
    task_index = {task.get("id"): task for task in tasks if isinstance(task, dict)}
    artifacts = [
        artifact
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
        and task_index.get(artifact.get("task_id"), {}).get("hive_id") == hive_id
    ]

    by_file: Dict[str, List[Dict[str, str]]] = {}
    weak_artifact_count = 0
    enriched_artifacts: List[Dict[str, Any]] = []
    for artifact in artifacts:
        task = task_index.get(artifact.get("task_id"), {})
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        quality = metadata.get("quality", "unknown")
        if quality == "incomplete":
            weak_artifact_count += 1
        enriched_artifacts.append(
            {
                **artifact,
                "role": artifact.get("role") or task.get("role", "WORKER"),
                "quality": {
                    "quality": quality,
                    "missing_outputs": metadata.get("missing_outputs", []),
                    "score": metadata.get("score"),
                },
            }
        )
        for path in NexusHiveEngine.extract_changed_files(str(artifact.get("content", ""))):
            by_file.setdefault(path, []).append(
                {"task_id": str(artifact.get("task_id", "")), "role": str(artifact.get("role", task.get("role", "WORKER")))}
            )

    conflicts = {
        path: entries
        for path, entries in sorted(by_file.items())
        if len({entry["task_id"] for entry in entries}) > 1
    }
    recommendations: List[str] = []
    if conflicts:
        recommendations.append("Resolve overlapping changed-file claims before merging Hive artifacts.")
    if weak_artifact_count:
        recommendations.append("Review incomplete artifacts and rerun affected Hive roles.")

    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "weak_artifact_count": weak_artifact_count,
        "artifacts": enriched_artifacts,
        "recommendations": recommendations,
    }


def load_hive_state(limit: int = 10) -> List[Dict[str, Any]]:
    """Return recent real hive progress from the persisted manifest."""
    data = _read_hive_manifest()
    if not data:
        return []

    hives: Dict[str, Dict[str, Any]] = {}
    signals_by_hive: Dict[str, List[Dict[str, Any]]] = {}
    blackboard_path = os.path.join(_ROOT, "logs", "hive", "hive_blackboard.jsonl")
    if os.path.exists(blackboard_path):
        try:
            with open(blackboard_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        signal = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(signal, dict):
                        continue
                    hive_id = str(signal.get("hive_id") or signal.get("hive") or "GLOBAL")
                    signals_by_hive.setdefault(hive_id, []).append(signal)
        except Exception:
            signals_by_hive = {}

    for task in data.get("tasks", []):
        hive_id = task.get("hive_id") or "unknown"
        item = hives.setdefault(
            hive_id,
            {
                "id": hive_id,
                "total": 0,
                "by_status": {},
                "roles": [],
                "tasks": [],
                "updated_at": 0,
            },
        )
        status = task.get("status", "unknown")
        role = task.get("role", "WORKER")
        item["total"] += 1
        item["by_status"][status] = item["by_status"].get(status, 0) + 1
        item["tasks"].append(
            {
                "id": task.get("id", ""),
                "role": role,
                "objective": task.get("objective", ""),
                "status": status,
                "attempts": task.get("attempts", 0),
                "error": task.get("error", ""),
                "result": task.get("result", ""),
                "updated_at": task.get("updated_at", 0),
            }
        )
        if role not in item["roles"]:
            item["roles"].append(role)
        item["updated_at"] = max(item["updated_at"], float(task.get("updated_at", 0) or 0))

    for hive_id, item in hives.items():
        insights = _hive_manifest_insights(hive_id, data)
        by_status = item.get("by_status", {})
        item.update(
            {
                "active_agents": by_status.get("running", 0),
                "paused_agents": by_status.get("pending", 0),
                "conflict_count": insights["conflict_count"],
                "conflicts": insights["conflicts"],
                "weak_artifact_count": insights["weak_artifact_count"],
                "signals": signals_by_hive.get(hive_id, [])[-10:],
            }
        )
        item["tasks"] = sorted(item["tasks"], key=lambda x: x.get("updated_at", 0), reverse=True)

    return sorted(hives.values(), key=lambda x: x["updated_at"], reverse=True)[:limit]


def load_reminders() -> List[Dict[str, Any]]:
    if not os.path.exists(_REMINDERS_PATH):
        return []
    try:
        with open(_REMINDERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        reminders = data if isinstance(data, list) else []
    except Exception:
        reminders = []
    now = time.time()
    normalized = []
    for item in reminders:
        if not isinstance(item, dict):
            continue
        due_at = float(item.get("due_at", 0) or 0)
        normalized.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "text": str(item.get("text") or "").strip(),
                "time": str(item.get("time") or (time.ctime(due_at) if due_at else "")),
                "due_at": due_at,
                "created_at": float(item.get("created_at", now) or now),
            }
        )
    return [item for item in normalized if item["text"]]


def save_reminders(reminders: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_REMINDERS_PATH), exist_ok=True)
    temp_path = f"{_REMINDERS_PATH}.{uuid.uuid4().hex[:8]}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2)
    os.replace(temp_path, _REMINDERS_PATH)


def build_provider_state(kernel) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build honest provider status from config instead of static claims."""
    cfg_data = kernel.config.data.get("providers", {})
    providers: List[Dict[str, Any]] = []
    instances: List[Dict[str, Any]] = []
    for section_name in ["cloud", "local"]:
        section = cfg_data.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for provider_id, provider_cfg in section.items():
            if not isinstance(provider_cfg, dict):
                continue
            active = bool(provider_cfg.get("active", False))
            api_key = str(provider_cfg.get("api_key", "") or "")
            is_local = section_name == "local"
            has_key = is_local or bool(api_key and "YOUR_" not in api_key and not api_key.startswith("sk-test"))
            if active and has_key:
                status = "ACTIVE"
            elif active:
                status = "AUTH_MISSING"
            else:
                status = "CONFIGURED"
            parent = provider_cfg.get("parent_provider", provider_id)
            model = provider_cfg.get("model", provider_cfg.get("default_model", provider_cfg.get("model_path", "")))
            endpoint = provider_cfg.get("endpoint", provider_cfg.get("base_url", ""))
            item = {
                "id": provider_id,
                "name": provider_id.upper(),
                "status": status,
                "profile": section_name,
                "parent": str(parent).upper(),
                "model": model,
                "endpoint": endpoint,
                "has_api_key": has_key,
                "description": f"{section_name.title()} provider profile for {parent}.",
            }
            providers.append(item)
            if active:
                instances.append(
                    {
                        "id": provider_id,
                        "parent": str(parent).upper(),
                        "model": model,
                        "endpoint": endpoint,
                        "has_api_key": has_key,
                        "profile": section_name,
                        "status": status,
                    }
                )
    providers.sort(key=lambda p: (p["status"] != "ACTIVE", p["profile"], p["id"]))
    return providers, instances


def build_tool_state(kernel) -> List[Dict[str, Any]]:
    """Build dashboard tool metadata. This is cached because discovery can be slow."""
    cfg = kernel.config.data
    custom_cfg = cfg.get("custom_tool_configs", {}) if isinstance(cfg, dict) else {}
    if not isinstance(custom_cfg, dict):
        custom_cfg = {}
    disabled = _config_disabled_set(cfg, "disabled_tools")
    deleted = _config_disabled_set(cfg, "deleted_tools")
    tools = []
    for t_name in kernel.tools.list_tools():
        if t_name in deleted:
            continue
        tool = kernel.tools.get(t_name)
        cfg_item = custom_cfg.get(t_name) or {}
        if not isinstance(cfg_item, dict):
            cfg_item = {}
        if tool:
            tools.append({"name": t_name, "description": cfg_item.get("description") or tool.description, "active": cfg_item.get("active", t_name not in disabled), "config": cfg_item})
    for name, cfg_item in custom_cfg.items():
        if name in deleted:
            continue
        if any(item["name"] == name for item in tools):
            continue
        if isinstance(cfg_item, dict):
            tools.append({"name": name, "description": cfg_item.get("description", ""), "active": cfg_item.get("active", True), "config": cfg_item})
    return tools


def _invalidate_dashboard_cache(*keys: str) -> None:
    targets = keys or ("state", "tools", "skills", "mcp", "providers")
    for key in targets:
        if key in _CACHE:
            _CACHE[key] = None
        last_key = f"{key}_last_update"
        if last_key in _CACHE:
            _CACHE[last_key] = 0


def _safe_slug(value: str, fallback: str = "plugin") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-_")
    return slug[:90] or fallback


def _config_disabled_set(config: Dict[str, Any], key: str) -> set:
    raw = config.get(key, [])
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(item) for item, enabled in raw.items() if enabled}
    return set()


def _read_plugin_manifest(path: str) -> Dict[str, Any]:
    candidates = [
        os.path.join(path, ".codex-plugin", "plugin.json"),
        os.path.join(path, "plugin.json"),
        os.path.join(path, "manifest.json"),
    ]
    for manifest_path in candidates:
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            print(f"[API_WARN] Failed to read plugin manifest {manifest_path}: {exc}")
    return {}


def _scan_plugin_assets(path: str) -> tuple[List[str], List[str]]:
    skills: List[str] = []
    tools: List[str] = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = os.path.relpath(root, path)
        if "SKILL.md" in files:
            skills.append(rel if rel != "." else os.path.basename(path))
        for filename in files:
            if not filename.endswith(".py"):
                continue
            file_path = os.path.join(root, filename)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(6000)
                if "BaseTool" in head or "class " in head and "Tool" in head:
                    tools.append(os.path.join(rel, filename) if rel != "." else filename)
            except Exception:
                continue
    return sorted(set(skills))[:50], sorted(set(tools))[:50]


def _plugin_marketplace_entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (
        cfg.get("plugin_marketplace")
        or cfg.get("plugin_catalog")
        or cfg.get("marketplace_plugins")
        or []
    )
    if isinstance(raw, dict):
        entries = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                entries.append(item)
            elif isinstance(value, str):
                entries.append({"id": key, "name": key, "source_url": value})
        return entries
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def discover_plugins() -> List[Dict[str, Any]]:
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    cfg = kernel.config.data
    disabled = _config_disabled_set(cfg, "disabled_plugins")
    deleted = _config_disabled_set(cfg, "deleted_plugins")
    roots = [
        ("plugins", os.path.join(_ROOT, "plugins")),
    ]
    plugins: List[Dict[str, Any]] = []
    seen = set()
    for source, root in roots:
        if not os.path.isdir(root):
            continue
        for item in os.listdir(root):
            if item.startswith(".") or item.startswith("__"):
                continue
            path = os.path.join(root, item)
            if not os.path.isdir(path):
                continue
            plugin_id = f"{source}:{item}"
            if plugin_id in seen or plugin_id in deleted:
                continue
            seen.add(plugin_id)
            manifest = _read_plugin_manifest(path)
            custom_config = cfg.get("plugin_configs", {}).get(plugin_id, {})
            if not isinstance(custom_config, dict):
                custom_config = {}
            desc = manifest.get("description") or manifest.get("summary")
            if not desc:
                for meta_file in ("README.md", "SKILL.md", "DESCRIPTION.md"):
                    meta_path = os.path.join(path, meta_file)
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, "r", encoding="utf-8", errors="ignore") as f:
                                desc = clean_description(f.read(3000))
                        except Exception:
                            pass
                        if desc:
                            break
            plugins.append(
                {
                    "id": plugin_id,
                    "name": custom_config.get("name") or manifest.get("name") or item,
                    "source": source,
                    "category": custom_config.get("category") or manifest.get("category"),
                    "install_kind": custom_config.get("install_kind") or manifest.get("install_kind") or ("repo" if source == "plugins" else source),
                    "version": custom_config.get("version") or manifest.get("version") or manifest.get("plugin_version") or "0.1.0",
                    "source_url": custom_config.get("source_url") or manifest.get("source_url") or manifest.get("repository"),
                    "installed_at": manifest.get("installed_at"),
                    "installed": True,
                    "path": path,
                    "display_path": os.path.relpath(path, _ROOT),
                    "description": custom_config.get("description") or desc or f"External NEXUS {source} bundle.",
                    "active": plugin_id not in disabled and manifest.get("active", True) is not False,
                    "removable": source == "plugins",
                    "disk_removable": source == "plugins",
                    "skills": [],
                    "tools": [],
                    "counts": {"skills": 0, "tools": 0},
                }
            )
    installed_urls = {str(plugin.get("source_url") or "").strip().lower() for plugin in plugins if plugin.get("source_url")}
    installed_names = {_safe_slug(str(plugin.get("name") or ""), "") for plugin in plugins}
    for entry in _plugin_marketplace_entries(cfg):
        name = str(entry.get("name") or entry.get("id") or "Marketplace Plugin").strip()
        slug = _safe_slug(str(entry.get("id") or name), "")
        if not slug:
            continue
        plugin_id = f"marketplace:{slug}"
        source_url = str(entry.get("source_url") or entry.get("repository") or entry.get("url") or "").strip()
        if plugin_id in seen or plugin_id in deleted:
            continue
        if source_url and source_url.lower() in installed_urls:
            continue
        if slug in installed_names:
            continue
        seen.add(plugin_id)
        plugins.append(
            {
                "id": plugin_id,
                "name": name,
                "source": "marketplace",
                "category": entry.get("category") or "marketplace",
                "install_kind": entry.get("install_kind") or entry.get("kind") or "plugin",
                "version": entry.get("version") or "available",
                "source_url": source_url,
                "installed": False,
                "path": "",
                "display_path": "not installed",
                "description": entry.get("description") or entry.get("summary") or "Available plugin. Install to download its source into NEXUS.",
                "active": False,
                "removable": False,
                "disk_removable": False,
                "skills": [],
                "tools": [],
                "counts": {"skills": 0, "tools": 0},
            }
        )
    return sorted(plugins, key=lambda p: (p["active"] is False, p["source"], p["name"].lower()))


def _normalize_repo_url(raw_url: str) -> tuple[str, str]:
    value = str(raw_url or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Plugin URL is required")
    if re.match(r"^[\w.-]+/[\w.-]+$", value):
        value = f"https://github.com/{value}.git"
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http", "git", "ssh"} and not value.startswith("git@"):
        raise HTTPException(status_code=400, detail="Use a Git URL or owner/repo")
    name = os.path.splitext(os.path.basename(parsed.path.rstrip("/")))[0] if parsed.path else "plugin"
    if value.startswith("git@"):
        name = os.path.splitext(value.rsplit("/", 1)[-1])[0]
    return value, _safe_slug(name)


def _download_github_zip(repo_url: str, target_dir: str) -> None:
    parsed = urlparse(repo_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.netloc.lower() not in {"github.com", "www.github.com"} or len(parts) < 2:
        raise RuntimeError("Git is unavailable and URL is not a simple GitHub repository")
    owner, repo = parts[0], os.path.splitext(parts[1])[0]
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"
    temp_zip = target_dir + ".zip"
    try:
        urllib.request.urlretrieve(zip_url, temp_zip)
    except Exception:
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip"
        urllib.request.urlretrieve(zip_url, temp_zip)
    temp_extract = target_dir + "_extract"
    with zipfile.ZipFile(temp_zip, "r") as archive:
        archive.extractall(temp_extract)
    entries = [os.path.join(temp_extract, entry) for entry in os.listdir(temp_extract)]
    if not entries:
        raise RuntimeError("Downloaded repository archive was empty")
    shutil.move(entries[0], target_dir)
    shutil.rmtree(temp_extract, ignore_errors=True)
    try:
        os.remove(temp_zip)
    except OSError:
        pass


def install_plugin_from_source(raw_url: str, kind: str = "plugin", force: bool = False, enable: bool = True) -> Dict[str, Any]:
    repo_url, slug = _normalize_repo_url(raw_url)
    kind = str(kind or "plugin").lower()
    install_root = os.path.abspath(os.path.join(_ROOT, "plugins"))
    os.makedirs(install_root, exist_ok=True)
    target = os.path.abspath(os.path.join(install_root, slug))
    if os.path.commonpath([install_root, target]) != install_root:
        raise HTTPException(status_code=400, detail="Invalid plugin target")
    if os.path.exists(target):
        if not force:
            raise HTTPException(status_code=409, detail=f"Plugin '{slug}' already exists. Enable force reinstall to replace it.")
        shutil.rmtree(target)
    try:
        subprocess.run(["git", "clone", "--depth", "1", repo_url, target], cwd=_ROOT, check=True, capture_output=True, text=True, timeout=120)
    except Exception as git_exc:
        try:
            _download_github_zip(repo_url, target)
        except Exception as zip_exc:
            raise HTTPException(status_code=500, detail=f"Install failed. git: {git_exc}; zip: {zip_exc}")

    manifest_dir = os.path.join(target, ".codex-plugin")
    manifest_path = os.path.join(manifest_dir, "plugin.json")
    if not os.path.exists(manifest_path):
        os.makedirs(manifest_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": slug,
                    "description": "External NEXUS plugin installed from source.",
                    "version": "0.1.0",
                    "install_kind": kind,
                    "source_url": repo_url,
                    "installed_at": time.time(),
                    "active": bool(enable),
                    "skills": [],
                    "tools": [],
                },
                f,
                indent=2,
            )
    return {"id": f"plugins:{slug}", "path": target, "url": repo_url}


def build_skill_state() -> List[Dict[str, Any]]:
    """Build the dashboard skill list from the on-disk skill registry."""
    try:
        from skills import NexusSkillMaster
        from kernel import get_nexus_kernel

        cfg = get_nexus_kernel(_ROOT).config.data
        custom_cfg = cfg.get("custom_skill_configs", {}) if isinstance(cfg, dict) else {}
        if not isinstance(custom_cfg, dict):
            custom_cfg = {}

        disabled = _config_disabled_set(cfg, "disabled_skills")
        deleted = _config_disabled_set(cfg, "deleted_skills")
        skills = []
        for skill in NexusSkillMaster(_ROOT).list_skills():
            name = skill.get("name") or skill.get("id", "Unnamed skill")
            skill_id = str(skill.get("id", name))
            if name in deleted or skill_id in deleted:
                continue
            cfg_item = custom_cfg.get(skill.get("id")) or custom_cfg.get(name) or {}
            if not isinstance(cfg_item, dict):
                cfg_item = {}
            skills.append(
                {
                    "id": skill_id,
                    "name": name,
                    "description": cfg_item.get("description") or skill.get("description", ""),
                    "category": skill.get("category"),
                    "active": cfg_item.get("active", name not in disabled and skill_id not in disabled),
                    "config": cfg_item,
                }
            )
        for name, cfg_item in custom_cfg.items():
            if name in deleted:
                continue
            if any(item["name"] == name or item["id"] == name for item in skills):
                continue
            if isinstance(cfg_item, dict):
                skills.append({"id": name, "name": name, "description": cfg_item.get("description", ""), "category": "custom", "active": cfg_item.get("active", True), "config": cfg_item})
        return skills
    except Exception as exc:
        print(f"[API_WARN] build_skill_state failed (non-fatal): {exc}")
        return []


def build_mcp_state(kernel) -> Dict[str, Any]:
    """Report configured MCP servers without forcing lazy MCP startup."""
    servers_cfg = kernel.config.data.get("mcp_servers", {})
    if not isinstance(servers_cfg, dict):
        servers_cfg = {}

    active_clients = getattr(kernel.tools, "_mcp_clients", {})
    servers = []
    for name, cfg in servers_cfg.items():
        if not isinstance(cfg, dict):
            cfg = {}
        active = bool(cfg.get("active", False))
        connected = name in active_clients
        servers.append(
            {
                "name": name,
                "status": "CONNECTED" if connected else ("CONFIGURED" if active else "DISABLED"),
                "active": active,
                "connected": connected,
                "command": cfg.get("command", ""),
                "description": cfg.get("description", ""),
            }
        )

    return {
        "connected": sum(1 for server in servers if server["connected"]),
        "total": len(servers),
        "servers": servers,
    }


def build_audit_state() -> Dict[str, Any]:
    """Return compact control-plane status. Never raises — returns empty on error."""
    try:
        from optimization.evidence_ledger import EvidenceLedger
        from optimization.mission_replay import MissionReplay
        from optimization.roadmap import RoadmapAuditor
        from optimization.tool_economy import ToolEconomy
        from optimization.unified_graph import UnifiedNexusGraph

        graph = UnifiedNexusGraph(_ROOT)
        loaded_graph = graph.load()
        if not loaded_graph.nodes:
            loaded_graph = graph.build(event_limit=100, include_code=False)
        roadmap = RoadmapAuditor(_ROOT).audit()
        return {
            "unified_graph": graph.summary(loaded_graph),
            "roadmap": {
                "total": roadmap["total"],
                "counts": roadmap["counts"],
                "completion_ratio": roadmap["completion_ratio"],
                "remaining_top": roadmap["remaining_top"][:5],
            },
            "evidence": EvidenceLedger(_ROOT).audit_summary(),
            "mission_replay": MissionReplay(_ROOT).recent(limit=12),
            "tool_economy": ToolEconomy(_ROOT).rank()[:12],
        }
    except Exception as exc:
        print(f"[API_WARN] build_audit_state failed (non-fatal): {exc}")
        return {
            "unified_graph": {"nodes": 0, "edges": 0},
            "roadmap": {"total": 0, "counts": {}, "completion_ratio": 0, "remaining_top": []},
            "evidence": {"total": 0, "by_status": {}},
            "mission_replay": [],
            "tool_economy": [],
        }


def _run_evolution_check(name: str, command: List[str], timeout: int = 90, cwd: str | None = None) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd or _ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {
            "name": name,
            "command": " ".join(command),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "duration_ms": int((time.time() - started) * 1000),
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "name": name,
            "command": " ".join(command),
            "ok": False,
            "returncode": None,
            "duration_ms": int((time.time() - started) * 1000),
            "stdout": "",
            "stderr": str(exc),
        }


def _python_with_module(module_name: str) -> List[str]:
    candidates: List[List[str]] = [
        [sys.executable],
        ["python"],
        ["py", "-3"],
        ["py", "-3.14"],
    ]
    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            probe = subprocess.run(
                candidate + ["-c", f"import {module_name}"],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=12,
                shell=False,
            )
            if probe.returncode == 0:
                return candidate
        except Exception:
            continue
    return [sys.executable]


def build_evolution_plan() -> Dict[str, Any]:
    from optimization.roadmap import RoadmapAuditor
    from evolution.context import EvolutionContextMap

    roadmap = RoadmapAuditor(_ROOT).audit()
    context = EvolutionContextMap(_ROOT).build()
    open_items = [item for item in roadmap.get("items", []) if item.get("status") != "done"]
    priority = open_items[:8]
    steps = []
    for index, item in enumerate(priority, start=1):
        steps.append(
            {
                "step": index,
                "title": item.get("item", "Unnamed evolution item"),
                "phase": item.get("phase", "Roadmap"),
                "status": item.get("status", "unknown"),
                "evidence": item.get("evidence", []),
                "remaining": item.get("remaining", []),
                "next_action": (item.get("remaining") or ["Add tests, implementation, and evidence for this item."])[0],
            }
        )

    plan = {
        "generated_at": time.time(),
        "roadmap": {
            "total": roadmap.get("total", 0),
            "counts": roadmap.get("counts", {}),
            "completion_ratio": roadmap.get("completion_ratio", 0),
        },
        "context_ready": context.get("ready", False),
        "recommendations": context.get("recommendations", []),
        "steps": steps,
        "commands": [
            "python -m py_compile gui/api.py optimization/roadmap.py evolution/context.py",
            "cd gui && npm run build",
            "python -m pytest tests/test_nextgen_power.py tests/test_evolution_context.py -q",
        ],
    }
    os.makedirs(os.path.join(_ROOT, "workspace"), exist_ok=True)
    with open(os.path.join(_ROOT, "workspace", "evolution_plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    return plan


def run_evolution_verification() -> Dict[str, Any]:
    from optimization.evidence_ledger import EvidenceLedger
    from optimization.roadmap import RoadmapAuditor

    pytest_python = _python_with_module("pytest")
    checks = [
        _run_evolution_check(
            "Python evolution compile gate",
            ["python", "-m", "py_compile", "gui/api.py", "optimization/roadmap.py", "evolution/context.py"],
            timeout=45,
        ),
        _run_evolution_check(
            "GUI build gate",
            ["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
            timeout=120,
            cwd=os.path.join(_ROOT, "gui"),
        ),
        _run_evolution_check(
            "Evolution regression tests",
            pytest_python + ["-m", "pytest", "tests/test_nextgen_power.py", "tests/test_evolution_context.py", "-q"],
            timeout=120,
        ),
    ]
    roadmap_path = RoadmapAuditor(_ROOT).write_status()
    ok = all(check.get("ok") for check in checks)
    record = EvidenceLedger(_ROOT).record_claim(
        "Evolution control plane verification ran real local compile, gui build, roadmap, and regression gates.",
        evidence=[
            {"source": check["command"], "detail": check["stderr"] or check["stdout"] or "completed", "kind": "command"}
            for check in checks
        ] + [{"source": roadmap_path, "detail": "Roadmap status regenerated from repository files.", "kind": "artifact"}],
        status="supported" if ok else "contradicted",
        confidence=0.95 if ok else 0.55,
        mission_id="gui:evolution",
    )
    _invalidate_dashboard_cache("state")
    with _AUDIT_LOCK:
        _CACHE["audit"] = build_audit_state()
        _CACHE["audit_last_update"] = time.time()
    return {
        "generated_at": time.time(),
        "ok": ok,
        "checks": checks,
        "roadmap_path": os.path.relpath(roadmap_path, _ROOT),
        "evidence_record": record.to_dict(),
    }


@app.get("/api/health")
def api_health():
    """Fast liveness probe for the Vite GUI (no kernel boot)."""
    return {"status": "ok", "service": "nexus-gui-api"}


@app.get("/api/state")
def get_state():
    now = time.time()
    if _CACHE["state"] and (now - _CACHE["last_update"]) < _STATE_TTL_SECONDS:
        return _CACHE["state"]
    if not _STATE_LOCK.acquire(blocking=False):
        if _CACHE["state"]:
            return _CACHE["state"]
        return {
            "hive": [],
            "skills": [],
            "tools": [],
            "plugins": [],
            "providers": [],
            "provider_instances": [],
            "mcp": {"connected": 0, "total": 0, "servers": []},
            "health": {"cpu": "0%", "ram": "0%", "status": "STARTING"},
            "session": {"active": True, "turns": 0},
            "reminders": load_reminders(),
            "audit": get_async_audit_state(),
        }

    try:
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel(_ROOT)

            tools = _cached_component("tools", _METADATA_TTL_SECONDS, lambda: build_tool_state(kernel), [])
            skills = _cached_component("skills", _METADATA_TTL_SECONDS, build_skill_state, [])
            mcp = _cached_component(
                "mcp",
                _METADATA_TTL_SECONDS,
                lambda: build_mcp_state(kernel),
                {"connected": 0, "total": 0, "servers": []},
            )
            providers_list, provider_instances = _cached_component(
                "providers",
                _METADATA_TTL_SECONDS,
                lambda: build_provider_state(kernel),
                ([], []),
            )
            stats = kernel.get_stats()
            health = {"cpu": stats["load"]["cpu"], "ram": stats["load"]["ram"], "status": stats["status"]}
        except Exception as exc:
            print(f"[API_WARN] kernel init failed: {exc}")
            tools = _CACHE.get("tools") or []
            skills = _cached_component("skills", _METADATA_TTL_SECONDS, build_skill_state, [])
            mcp = _CACHE.get("mcp") or {"connected": 0, "total": 0, "servers": []}
            providers_list, provider_instances = _CACHE.get("providers") or ([], [])
            health = {"cpu": "0%", "ram": "0%", "status": "DEGRADED"}

        result = {
            "hive": load_hive_state(),
            "skills": skills,
            "tools": tools,
            "plugins": discover_plugins(),
            "providers": providers_list,
            "provider_instances": provider_instances,
            "mcp": mcp,
            "health": health,
            "session": {"active": True, "turns": 0},
            "reminders": load_reminders(),
            "audit": get_async_audit_state(),
        }

        _CACHE["state"] = result
        _CACHE["last_update"] = time.time()
        return result
    finally:
        _STATE_LOCK.release()


@app.post("/api/reminders")
async def create_reminder(data: dict, request: Request):
    require_config_write_allowed(request)
    text = str(data.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reminder text is required")
    due_at = float(data.get("due_at", 0) or 0)
    reminder = {
        "id": f"rem_{uuid.uuid4().hex[:10]}",
        "text": text,
        "time": str(data.get("time") or (time.ctime(due_at) if due_at else time.strftime("%H:%M:%S"))),
        "due_at": due_at,
        "created_at": time.time(),
    }
    reminders = [reminder, *load_reminders()]
    save_reminders(reminders)
    _invalidate_dashboard_cache("state")
    return {"status": "success", "reminder": reminder, "reminders": reminders}


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str, request: Request):
    require_config_write_allowed(request)
    reminders = [item for item in load_reminders() if item.get("id") != reminder_id]
    save_reminders(reminders)
    _invalidate_dashboard_cache("state")
    return {"status": "success", "reminders": reminders}


@app.get("/api/audit")
def get_audit_state():
    return build_audit_state()


@app.post("/api/evolution/plan")
async def evolution_plan(request: Request):
    require_config_write_allowed(request)
    plan = build_evolution_plan()
    return {"status": "success", "message": "Evolution plan generated from current roadmap and context.", "plan": plan}


@app.post("/api/evolution/verify")
async def evolution_verify(request: Request):
    require_config_write_allowed(request)
    result = run_evolution_verification()
    return {"status": "success" if result.get("ok") else "error", "message": "Evolution verification completed.", "result": result}


@app.get("/api/config")
def get_config():
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    return kernel.config.data


@app.post("/api/config")
async def save_config(data: dict, request: Request):
    require_config_write_allowed(request)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Config payload must be an object")
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    kernel.config.data = data
    if not kernel.config.save():
        raise HTTPException(status_code=500, detail="Failed to save active profile config")
    if hasattr(kernel.config, "reload"):
        kernel.config.reload()
    _invalidate_dashboard_cache()
    return {"status": "success", "message": "Configuration saved."}


@app.get("/api/plugins")
def list_plugins():
    return {"plugins": discover_plugins()}


@app.post("/api/plugins/install")
async def install_plugin(data: dict, request: Request):
    require_config_write_allowed(request)
    installed = install_plugin_from_source(
        data.get("url", ""),
        kind=data.get("kind", "plugin"),
        force=bool(data.get("force", False)),
        enable=bool(data.get("enable", True)),
    )
    _invalidate_dashboard_cache()
    return {"status": "success", "message": f"Installed {installed['id']} into plugins/.", **installed}


@app.post("/api/plugins/create")
async def create_local_plugin(data: dict, request: Request):
    require_config_write_allowed(request)
    name = _safe_slug(str(data.get("name", "")), "")
    if not name:
        raise HTTPException(status_code=400, detail="Plugin name is required")
    description = str(data.get("description", "")).strip() or "Custom local NEXUS plugin."
    version = str(data.get("version", "0.1.0")).strip() or "0.1.0"
    install_kind = str(data.get("kind", "custom")).strip() or "custom"

    plugin_root = os.path.abspath(os.path.join(_ROOT, "plugins"))
    target = os.path.abspath(os.path.join(plugin_root, name))
    if os.path.commonpath([plugin_root, target]) != plugin_root:
        raise HTTPException(status_code=400, detail="Invalid plugin name")
    if os.path.exists(target):
        raise HTTPException(status_code=409, detail=f"Plugin '{name}' already exists")

    os.makedirs(os.path.join(target, ".codex-plugin"), exist_ok=True)
    os.makedirs(os.path.join(target, "skills"), exist_ok=True)
    os.makedirs(os.path.join(target, "tools"), exist_ok=True)
    manifest = {
        "name": name,
        "description": description,
        "version": version,
        "install_kind": install_kind,
        "source": "local",
        "installed_at": time.time(),
        "active": True,
        "skills": [],
        "tools": [],
    }
    with open(os.path.join(target, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n{description}\n\nVersion: {version}\n")
    _invalidate_dashboard_cache()
    return {"status": "success", "message": f"Created plugin '{name}'.", "id": f"plugins:{name}", "path": target}


@app.post("/api/plugins/configure")
async def configure_plugin(data: dict, request: Request):
    require_config_write_allowed(request)
    plugin_id = str(data.get("id", "")).strip()
    if not plugin_id:
        raise HTTPException(status_code=400, detail="Plugin id is required")
    active = bool(data.get("active", True))
    plugin_config = data.get("config")

    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    cfg = kernel.config.data
    disabled = sorted(_config_disabled_set(cfg, "disabled_plugins"))
    if active:
        disabled = [item for item in disabled if item != plugin_id]
    elif plugin_id not in disabled:
        disabled.append(plugin_id)
    cfg["disabled_plugins"] = disabled
    if isinstance(plugin_config, dict):
        registry = cfg.setdefault("plugin_configs", {})
        saved = dict(plugin_config)
        saved["active"] = active
        registry[plugin_id] = saved
    if not kernel.config.save():
        raise HTTPException(status_code=500, detail="Failed to save plugin configuration")
    _invalidate_dashboard_cache()
    return {"status": "success", "message": f"Plugin {'enabled' if active else 'disabled'}."}


@app.delete("/api/plugins/{plugin_id:path}")
async def delete_plugin(plugin_id: str, request: Request):
    require_config_write_allowed(request)
    plugin_id = str(plugin_id or "").strip()
    plugins = {plugin["id"]: plugin for plugin in discover_plugins()}
    plugin = plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    cfg = kernel.config.data
    if plugin.get("disk_removable"):
        path = os.path.abspath(plugin.get("path", ""))
        plugin_root = os.path.abspath(os.path.join(_ROOT, "plugins"))
        if os.path.commonpath([plugin_root, path]) != plugin_root:
            raise HTTPException(status_code=400, detail="Plugin path is outside plugins/")
        shutil.rmtree(path, ignore_errors=True)
        message = "Plugin removed from disk."
    else:
        deleted = sorted(_config_disabled_set(cfg, "deleted_plugins"))
        if plugin_id not in deleted:
            deleted.append(plugin_id)
        cfg["deleted_plugins"] = deleted
        if not kernel.config.save():
            raise HTTPException(status_code=500, detail="Failed to save plugin removal")
        message = "Plugin hidden from inventory."
    _invalidate_dashboard_cache()
    return {"status": "success", "message": message}


@app.post("/api/assets/{asset_kind}/configure")
async def configure_asset(asset_kind: str, data: dict, request: Request):
    require_config_write_allowed(request)
    if asset_kind not in {"skills", "tools"}:
        raise HTTPException(status_code=404, detail="Unknown asset kind")
    name = _safe_slug(str(data.get("name", "")), "")
    if not name:
        raise HTTPException(status_code=400, detail="Asset name is required")
    config = data.get("config", {})
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Asset config must be an object")

    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    key = "custom_skill_configs" if asset_kind == "skills" else "custom_tool_configs"
    registry = kernel.config.data.setdefault(key, {})
    registry[name] = config
    disabled_key = "disabled_skills" if asset_kind == "skills" else "disabled_tools"
    disabled = sorted(_config_disabled_set(kernel.config.data, disabled_key))
    if config.get("active", True) is False:
        if name not in disabled:
            disabled.append(name)
    else:
        disabled = [item for item in disabled if item != name]
    kernel.config.data[disabled_key] = disabled
    description_key = "custom_skill_descriptions" if asset_kind == "skills" else "custom_tool_descriptions"
    if config.get("description"):
        kernel.config.data.setdefault(description_key, {})[name] = str(config.get("description"))
    if not kernel.config.save():
        raise HTTPException(status_code=500, detail=f"Failed to save {asset_kind} config")
    _invalidate_dashboard_cache("state", "skills" if asset_kind == "skills" else "tools")
    return {"status": "success", "message": f"{asset_kind[:-1].title()} '{name}' saved."}


async def _delete_asset_config(asset_kind: str, name: str, request: Request):
    require_config_write_allowed(request)
    if asset_kind not in {"skills", "tools"}:
        raise HTTPException(status_code=404, detail="Unknown asset kind")
    item_name = _safe_slug(str(name), "")
    if not item_name:
        raise HTTPException(status_code=400, detail="Asset name is required")
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    deleted_key = "deleted_skills" if asset_kind == "skills" else "deleted_tools"
    deleted = sorted(_config_disabled_set(kernel.config.data, deleted_key))
    if item_name not in deleted:
        deleted.append(item_name)
    kernel.config.data[deleted_key] = deleted
    disabled_key = "disabled_skills" if asset_kind == "skills" else "disabled_tools"
    disabled = sorted(_config_disabled_set(kernel.config.data, disabled_key))
    if item_name not in disabled:
        disabled.append(item_name)
    kernel.config.data[disabled_key] = disabled
    custom_key = "custom_skill_configs" if asset_kind == "skills" else "custom_tool_configs"
    if isinstance(kernel.config.data.get(custom_key), dict):
        kernel.config.data[custom_key].pop(item_name, None)
    if not kernel.config.save():
        raise HTTPException(status_code=500, detail=f"Failed to delete {asset_kind[:-1]}")
    _invalidate_dashboard_cache("state", "skills" if asset_kind == "skills" else "tools")
    return {"status": "success", "message": f"{asset_kind[:-1].title()} '{item_name}' hidden."}


@app.delete("/api/skills/delete/{name}")
async def delete_skill_asset(name: str, request: Request):
    return await _delete_asset_config("skills", name, request)


@app.delete("/api/tools/delete/{name}")
async def delete_tool_asset(name: str, request: Request):
    return await _delete_asset_config("tools", name, request)

# ── Hive Persona Management ──────────────────────────────────────────────────

@app.get("/api/hive/personas")
def list_hive_personas():
    from kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    return kernel.hive.list_personas()

@app.post("/api/hive/personas")
async def create_hive_persona(data: dict, request: Request):
    require_config_write_allowed(request)
    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        raise HTTPException(status_code=400, detail="Name and description are required")
    
    from kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.create_persona(name, description)
    if success:
        return {"status": "success", "message": f"Persona '{name}' created."}
    return {"status": "error", "message": f"Persona '{name}' already exists or is reserved."}

@app.put("/api/hive/personas/{name}")
async def modify_hive_persona(name: str, data: dict, request: Request):
    require_config_write_allowed(request)
    description = data.get("description")
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    
    from kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.modify_persona(name, description)
    if success:
        return {"status": "success", "message": f"Persona '{name}' updated."}
    return {"status": "error", "message": f"Persona '{name}' not found or is reserved."}

@app.delete("/api/hive/personas/{name}")
async def delete_hive_persona(name: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.delete_persona(name)
    if success:
        return {"status": "success", "message": f"Persona '{name}' deleted."}
    return {"status": "error", "message": f"Persona '{name}' not found or is reserved."}


@app.post("/api/hive/missions")
async def create_hive_mission(data: dict, request: Request):
    require_config_write_allowed(request)
    mission = str(data.get("mission", "")).strip()
    if not mission:
        raise HTTPException(status_code=400, detail="Mission is required")
    autostart = bool(data.get("autostart", True))
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    hive_id = kernel.hive.create_mission(mission, autostart=autostart)
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "hive": load_hive_state()}


@app.post("/api/hive/{hive_id}/pause")
async def pause_hive(hive_id: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    count = kernel.hive.cancel_hive(hive_id)
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "paused": count, "hive": load_hive_state()}


@app.post("/api/hive/{hive_id}/stop")
async def stop_hive(hive_id: str, request: Request):
    return await pause_hive(hive_id, request)


@app.delete("/api/hive/{hive_id}")
async def remove_hive(hive_id: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    with kernel.hive._lock:
        task_ids = {task.id for task in kernel.hive._tasks.values() if task.hive_id == hive_id}
        for task_id in list(task_ids):
            kernel.hive._tasks.pop(task_id, None)
        kernel.hive._artifacts = [artifact for artifact in kernel.hive._artifacts if artifact.task_id not in task_ids]
        kernel.hive._contracts = {
            contract_id: contract
            for contract_id, contract in kernel.hive._contracts.items()
            if contract.hive_id != hive_id
        }
        kernel.hive._handoffs = {
            handoff_id: handoff
            for handoff_id, handoff in kernel.hive._handoffs.items()
            if handoff.hive_id != hive_id
        }
        kernel.hive._cancelled.discard(hive_id)
        kernel.hive._persist_manifest()
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "removed": len(task_ids), "hive": load_hive_state()}


@app.post("/api/hive/{hive_id}/tasks/{task_id}/stop")
async def stop_hive_task(hive_id: str, task_id: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    with kernel.hive._lock:
        task = kernel.hive._tasks.get(task_id)
        if not task or task.hive_id != hive_id:
            raise HTTPException(status_code=404, detail="Hive task not found")
        task.status = "cancelled"
        task.updated_at = time.time()
        kernel.hive._persist_manifest()
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "task_id": task_id, "hive": load_hive_state()}


@app.post("/api/hive/{hive_id}/tasks/{task_id}/resume")
async def resume_hive_task(hive_id: str, task_id: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    with kernel.hive._lock:
        task = kernel.hive._tasks.get(task_id)
        if not task or task.hive_id != hive_id:
            raise HTTPException(status_code=404, detail="Hive task not found")
        task.status = "pending"
        task.updated_at = time.time()
        kernel.hive._queue.put(task.id)
        kernel.hive._cancelled.discard(hive_id)
        kernel.hive._persist_manifest()
    kernel.hive.start_workers()
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "task_id": task_id, "hive": load_hive_state()}


@app.delete("/api/hive/{hive_id}/tasks/{task_id}")
async def remove_hive_task(hive_id: str, task_id: str, request: Request):
    require_config_write_allowed(request)
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    with kernel.hive._lock:
        task = kernel.hive._tasks.get(task_id)
        if not task or task.hive_id != hive_id:
            raise HTTPException(status_code=404, detail="Hive task not found")
        kernel.hive._tasks.pop(task_id, None)
        kernel.hive._artifacts = [artifact for artifact in kernel.hive._artifacts if artifact.task_id != task_id]
        kernel.hive._contracts = {
            contract_id: contract
            for contract_id, contract in kernel.hive._contracts.items()
            if contract.task_id != task_id
        }
        kernel.hive._handoffs = {
            handoff_id: handoff
            for handoff_id, handoff in kernel.hive._handoffs.items()
            if handoff.task_id != task_id
        }
        kernel.hive._persist_manifest()
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "task_id": task_id, "hive": load_hive_state()}


@app.get("/api/hive/{hive_id}/merge-plan")
def get_hive_merge_plan(hive_id: str):
    manifest = _read_hive_manifest()
    if not manifest:
        raise HTTPException(status_code=404, detail="Hive manifest not found")
    insights = _hive_manifest_insights(hive_id, manifest)
    return {
        "hive_id": hive_id,
        "conflicts": insights["conflicts"],
        "conflict_count": insights["conflict_count"],
        "artifacts": insights["artifacts"],
        "recommendations": insights["recommendations"],
    }


@app.post("/api/hive/{hive_id}/resume")
async def resume_hive(hive_id: str, request: Request):
    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    return kernel.hive.resume_hive(hive_id)


@app.post("/api/mcp/configure")
async def configure_mcp_server(data: dict, request: Request):
    require_config_write_allowed(request)
    name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    config = data.get("config")
    if not name or not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="MCP server name and config object are required")

    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    servers = kernel.config.data.setdefault("mcp_servers", {})
    servers[name] = config
    if not kernel.config.save():
        raise HTTPException(status_code=500, detail="Failed to persist MCP server configuration")
    return {"status": "success", "name": name}


@app.delete("/api/mcp/delete/{name}")
async def delete_mcp_server(name: str, request: Request):
    require_config_write_allowed(request)
    server_name = re.sub(r"[^a-z0-9_-]", "", str(name).lower())
    if not server_name:
        raise HTTPException(status_code=400, detail="Invalid MCP server name")

    from kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    servers = kernel.config.data.setdefault("mcp_servers", {})
    if server_name in servers:
        del servers[server_name]
        if not kernel.config.save():
            raise HTTPException(status_code=500, detail="Failed to persist MCP server configuration")
    return {"status": "success", "name": server_name}


@app.get("/api/vision/accelerator")
def get_vision_accelerator_state():
    from tools.nexus_tools.vision.vision_accelerator_tool import VisionAccelerator

    return VisionAccelerator().status()


def _provider_config_path() -> str:
    return os.path.join(_ROOT, "configs", "nexus_config.yaml")


def _load_provider_config() -> Dict[str, Any]:
    config_path = _provider_config_path()
    if not os.path.exists(config_path):
        raise HTTPException(status_code=500, detail="Global configuration file (nexus_config.yaml) is missing.")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=500, detail="Provider configuration is invalid.")
    cfg.setdefault("providers", {}).setdefault("cloud", {})
    cfg.setdefault("providers", {}).setdefault("local", {})
    return cfg


def _save_provider_config(cfg: Dict[str, Any]) -> None:
    with open(_provider_config_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    _invalidate_dashboard_cache("state", "providers")


@app.post("/api/providers/add")
async def add_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider_type_name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    if not provider_type_name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    profile = str(data.get("profile", "cloud")).lower()
    target_section = "local" if profile == "local" or provider_type_name in {"ollama", "lm_studio", "llama_cpp"} else "cloud"
    cfg = _load_provider_config()
    section = cfg["providers"].setdefault(target_section, {})
    if provider_type_name not in section:
        section[provider_type_name] = {"active": True, "parent_provider": provider_type_name}
    section[provider_type_name]["active"] = True
    section[provider_type_name]["parent_provider"] = provider_type_name
    endpoint = str(data.get("endpoint", "")).strip()
    if endpoint:
        section[provider_type_name]["endpoint"] = endpoint
    _save_provider_config(cfg)
    return {"status": "success", "message": f"Provider '{provider_type_name}' saved."}


@app.post("/api/providers/ping")
async def ping_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    endpoint = str(data.get("endpoint", "")).strip()
    started = time.time()
    if not endpoint:
        return {"ok": True, "status": "success", "message": "No endpoint configured; provider route is locally editable.", "latency_ms": 0}
    try:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Endpoint must be http or https")
        req = urllib.request.Request(endpoint, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as response:
            latency = int((time.time() - started) * 1000)
            return {"ok": True, "status": "success", "message": f"Endpoint responded with HTTP {response.status}.", "latency_ms": latency}
    except Exception as exc:
        latency = int((time.time() - started) * 1000)
        return {"ok": False, "status": "error", "message": str(exc), "latency_ms": latency}


@app.post("/api/providers/test")
async def test_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider_name = str(data.get("name", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    endpoint = str(data.get("endpoint", "")).strip()
    if endpoint:
        return await ping_provider(data, request)
    if api_key or provider_name.lower() in {"ollama", "lm_studio", "llama_cpp"}:
        return {"ok": True, "status": "success", "message": "Provider credentials/config are present. Save the route to use it."}
    return {"ok": False, "status": "error", "message": "Add an API key or endpoint before testing this provider."}


@app.post("/api/providers/configure")
async def configure_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider_type_name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    instance_id = re.sub(r"[^a-z0-9_-]", "-", str(data.get("instance_id", provider_type_name)).lower()).strip("-")
    api_key = str(data.get("api_key", "")).strip()
    model = str(data.get("model", "")).strip()
    endpoint = str(data.get("endpoint", "")).strip()
    if not provider_type_name or not instance_id:
        raise HTTPException(status_code=400, detail="Provider name and instance id are required")
    
    config_path = _provider_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f)
            
            if "providers" not in cfg: cfg["providers"] = {"cloud": {}, "local": {}}
            if "cloud" not in cfg["providers"]: cfg["providers"]["cloud"] = {}
            if "local" not in cfg["providers"]: cfg["providers"]["local"] = {}
            
            target_section = "cloud"
            if provider_type_name in ["ollama", "lm_studio", "llama_cpp"]:
                target_section = "local"
            
            if instance_id not in cfg["providers"][target_section]:
                cfg["providers"][target_section][instance_id] = {"active": True}
            
            conf = cfg["providers"][target_section][instance_id]
            conf["active"] = True
            conf["parent_provider"] = provider_type_name
            if api_key: conf["api_key"] = api_key
            if model: conf["model"] = model
            if endpoint: conf["endpoint"] = endpoint
            
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
            _invalidate_dashboard_cache("state", "providers")
            
            return {"status": "success", "message": f"Configuration '{instance_id}' saved."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Config file not found."}

@app.delete("/api/providers/instance/{instance_id}")
async def delete_provider_instance(instance_id: str, request: Request):
    require_config_write_allowed(request)
    instance_id = re.sub(r"[^a-z0-9_-]", "-", str(instance_id).lower()).strip("-")
    if not instance_id:
        raise HTTPException(status_code=400, detail="Invalid instance id")
    config_path = _provider_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f)
            
            # Search in local and cloud
            deleted = False
            prov_root = cfg.get("providers", {})
            for p_type in ["local", "cloud"]:
                section = prov_root.get(p_type, {})
                if instance_id in section:
                    del section[instance_id]
                    deleted = True
                    break
            
            if deleted:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
                _invalidate_dashboard_cache("state", "providers")
                return {"status": "success", "message": f"Instance {instance_id} deleted."}
            return {"status": "error", "message": f"Instance {instance_id} not found."}
        except Exception as e:
            return {"status": "error", "message": f"Configuration deletion failure: {str(e)}"}
    return {"status": "error", "message": "Global configuration file (nexus_config.yaml) is missing."}

# -- Vision streaming state ---------------------------------------------------
_VISION_MODEL      = None        # yolo11n detect (cached)
_VISION_SEG_MODEL  = None        # yolo11n-seg   (cached)
_VISION_POSE_MODEL = None        # yolo11n-pose  (cached)
_VISION_CAP        = None        # active cv2.VideoCapture
_VISION_ACTIVE     = False       # False = stop stream loop
_FACE_CASCADE      = None        # OpenCV Haar cascade (cached)
_ONNX_SESSIONS: Dict[str, Any] = {}
_ACTIVE_MODES: set = {"objects"}   # HOT-SWAP: updated by /api/vision/modes without restart
_MODELS_READY     = False       # set True once preload finishes
_LOW_MEM_MODE     = False       # set True if system is memory constrained
_MP_HANDS         = None        # MediaPipe Hands (cached)

_BODY_SKELETON = [
    (0,1),(0,2),(1,3),(2,4),(5,7),(7,9),(6,8),(8,10),
    (5,6),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16),
]
_HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),
    (0,9),(9,10),(10,11),(11,12),(0,13),(13,14),(14,15),(15,16),
    (0,17),(17,18),(18,19),(19,20),
]

# ── Model loaders (idempotent – load once, never reload) ─────────────────────
def _load_yolo_detect():
    global _VISION_MODEL
    if _VISION_MODEL is not None:
        return _VISION_MODEL, None
    try:
        from ultralytics import YOLO
        p_ov = os.path.join(_ROOT, "models", "local", "vision", "yolo11n_openvino_model")
        p_pt = os.path.join(_ROOT, "models", "local", "vision", "yolo11n.pt")
        p = p_ov if os.path.exists(p_ov) else p_pt
        if not os.path.exists(p):
            return None, "YOLO model not found"
        # Load model and task. If it's OpenVINO, it will use Intel iGPU if possible.
        _VISION_MODEL = YOLO(p, task="detect")
        return _VISION_MODEL, None
    except Exception as e:
        return None, str(e)

def _load_yolo_seg():
    global _VISION_SEG_MODEL
    if _VISION_SEG_MODEL is not None:
        return _VISION_SEG_MODEL, None
    try:
        from ultralytics import YOLO
        p_ov = os.path.join(_ROOT, "models", "local", "vision", "yolo11n-seg_openvino_model")
        p_pt = os.path.join(_ROOT, "models", "local", "vision", "yolo11n-seg.pt")
        p = p_ov if os.path.exists(p_ov) else p_pt
        if not os.path.exists(p):
            return None, "YOLO Seg model not found"
        _VISION_SEG_MODEL = YOLO(p, task="segment")
        return _VISION_SEG_MODEL, None
    except Exception as e:
        return None, str(e)

def _load_yolo_pose():
    global _VISION_POSE_MODEL
    if _VISION_POSE_MODEL is not None:
        return _VISION_POSE_MODEL, None
    try:
        from ultralytics import YOLO
        p = os.path.join(_ROOT, "models", "local", "vision", "yolo11n-pose.pt")
        if not os.path.exists(p):
            return None, "YOLO Pose model not found"
        _VISION_POSE_MODEL = YOLO(p, task="pose")
        return _VISION_POSE_MODEL, None
    except Exception as e:
        return None, str(e)

def _load_face_cascade():
    global _FACE_CASCADE
    if _FACE_CASCADE is not None:
        return _FACE_CASCADE, None
    try:
        import cv2
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cc.empty():
            return None, "Haar cascade not found"
        _FACE_CASCADE = cc
        return _FACE_CASCADE, None
    except Exception as e:
        return None, str(e)

def _get_mp_hands():
    """Idempotent MediaPipe Hand Landmarker (V2 Tasks API) loader."""
    global _MP_HANDS
    if _MP_HANDS is not None:
        return _MP_HANDS, None
    try:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        model_path = os.path.join(_ROOT, "models", "local", "mediapipe", "tasks", "vision", "hand_landmarker.task")
        if not os.path.exists(model_path):
            return None, "hand_landmarker.task not found"
            
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            running_mode=vision.RunningMode.IMAGE
        )
        _MP_HANDS = vision.HandLandmarker.create_from_options(options)
        return _MP_HANDS, None
    except Exception as e:
        return None, str(e)

def _load_onnx(filename: str):
    if filename in _ONNX_SESSIONS:
        return _ONNX_SESSIONS[filename], None
    try:
        import onnxruntime as ort
        p = os.path.join(_ROOT, "models", "local", "vision", filename)
        if not os.path.exists(p):
            return None, f"{filename} not found"
        
        # 🚀 [IGPU_ACCELERATION]: Prioritize DirectML and OpenVINO for Intel iGPU
        providers = [
            "DmlExecutionProvider",          # Best for Windows iGPU/dGPU
            "OpenVINOExecutionProvider",     # Best for Intel specifically
            "CPUExecutionProvider"
        ]
        
        try:
            sess = ort.InferenceSession(p, providers=providers)
        except Exception as e:
            logger.warning(f"Failed to load {filename} with GPU providers: {e}. Falling back to CPU.")
            sess = ort.InferenceSession(p, providers=["CPUExecutionProvider"])
            
        _ONNX_SESSIONS[filename] = sess
        return sess, None
    except ImportError:
        return None, "onnxruntime not installed"
    except Exception as e:
        return None, str(e)

def _preload_models_bg():
    """Load all models in a background thread at server startup with memory awareness."""
    def _do():
        global _MODELS_READY, _LOW_MEM_MODE
        try:
            import psutil
            import time
            mem = psutil.virtual_memory()
            print(f"[VISION] Memory Check: {mem.percent}% used.")
            
            if mem.percent > 92:
                print("[VISION] ⚠️ CRITICAL MEMORY: Skipping background preload.")
                _LOW_MEM_MODE = True
                _MODELS_READY = True
                return

            print("[VISION] Preloading models in background…")
            _load_yolo_detect()
            time.sleep(1.0) # Prevent burst memory spikes
            _load_yolo_seg()
            time.sleep(1.0)
            _load_face_cascade()
            
            for fname in [
                "rtmpose-m_simcc-hand5_pt-aic-coco_210e-256x256-74fb594_20230320.onnx",
                "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx",
            ]:
                try:
                    _load_onnx(fname)
                    time.sleep(0.5)
                except Exception:
                    pass
            _MODELS_READY = True
            print("[VISION] Models ready.")
        except Exception as e:
            print(f"[VISION] Preload error: {e}")
            _MODELS_READY = True

    threading.Thread(target=_do, daemon=True).start()

# Start preloading immediately when api.py is imported
_preload_models_bg()

# 🛡️ [INFERENCE_MESH]: Parallel execution pool
_VISION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=5)

# ── Per-mode processors ───────────────────────────────────────────────────────
def _proc_objects(frame, draw):
    import cv2
    model, err = _load_yolo_detect()
    if err:
        cv2.putText(draw, f"obj:{err[:40]}", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 60, 60), 1)
        return draw
    results = model(frame, verbose=False)[0]
    for box in results.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        lbl = f"{results.names[int(box.cls[0])]} {float(box.conf[0]):.2f}"
        cv2.rectangle(draw, (x1, y1), (x2, y2), (59, 130, 246), 2)
        cv2.putText(draw, lbl, (x1, max(y1 - 5, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (59, 130, 246), 2)
    return draw

def _proc_segment(frame, draw):
    import cv2, numpy as np
    model, err = _load_yolo_seg()
    if err:
        cv2.putText(draw, f"seg:{err[:40]}", (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 60, 255), 1)
        return draw
    results = model(frame, verbose=False)[0]
    colors = [(139, 92, 246), (99, 102, 241), (168, 85, 247), (192, 38, 211), (109, 40, 217)]
    if results.masks is not None:
        for i, mask in enumerate(results.masks.data.cpu().numpy()):
            m = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
            col = colors[i % len(colors)]
            ov = draw.copy()
            ov[m > 0.5] = col
            draw = cv2.addWeighted(draw, 0.55, ov, 0.45, 0)
    for box in results.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cv2.rectangle(draw, (x1, y1), (x2, y2), (139, 92, 246), 2)
    return draw

def _proc_face(frame, draw):
    import cv2
    cascade, err = _load_face_cascade()
    if err:
        cv2.putText(draw, f"face:{err[:40]}", (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 191, 36), 1)
        return draw
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    for (x, y, w, h) in faces:
        cv2.rectangle(draw, (x, y), (x + w, y + h), (0, 220, 200), 2)
        cv2.putText(draw, "Face", (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 200), 2)
    return draw

def _proc_hand(frame, draw):
    import cv2
    import mediapipe as mp
    hands, err = _get_mp_hands()
    if err:
        cv2.putText(draw, f"hand:{err[:40]}", (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (16, 185, 129), 1)
        return draw
    
    # MediaPipe Tasks uses mp.Image
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    results = hands.detect(mp_image)
    
    if results.hand_landmarks:
        h, w = frame.shape[:2]
        for hand_landmarks in results.hand_landmarks:
            px = []
            py = []
            for lm in hand_landmarks:
                px.append(int(lm.x * w))
                py.append(int(lm.y * h))
            
            # Draw connections matching NEXUS style
            for (a, b) in _HAND_CONNECTIONS:
                if a < len(px) and b < len(px):
                    cv2.line(draw, (px[a], py[a]), (px[b], py[b]), (16, 185, 129), 2)
            
            # Draw joints
            for i in range(len(px)):
                cv2.circle(draw, (px[i], py[i]), 4, (255, 255, 255), -1)
                cv2.circle(draw, (px[i], py[i]), 3, (16, 185, 129), 2)
                
    return draw

def _proc_body(frame, draw):
    import cv2
    fname = "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx"
    sess, err = _load_onnx(fname)
    if err:
        cv2.putText(draw, f"body:{err[:40]}", (8, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (236, 72, 153), 1)
        return draw
    return _run_rtmpose(frame, draw, sess, (192, 256), _BODY_SKELETON, (236, 72, 153))

def _proc_yolo_pose(frame, draw):
    import cv2
    model, err = _load_yolo_pose()
    if err:
        cv2.putText(draw, f"y-pose:{err[:40]}", (8, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 100, 0), 1)
        return draw
    results = model(frame, verbose=False)[0]
    if results.keypoints is not None:
        for kp in results.keypoints.xy.cpu().numpy():
            for x, y in kp:
                if x > 0 and y > 0:
                    cv2.circle(draw, (int(x), int(y)), 4, (255, 100, 0), -1)
    return draw

def _run_rtmpose(frame, draw, sess, input_wh, connections, color):
    import cv2, numpy as np
    H, W = frame.shape[:2]
    iw, ih = input_wh
    img = cv2.resize(frame, (iw, ih)).astype(np.float32)
    img = (img[:, :, ::-1] - [123.675, 116.28, 103.53]) / [58.395, 57.12, 57.375]
    inp = img.transpose(2, 0, 1)[None].astype(np.float32)
    try:
        outs = sess.run(None, {sess.get_inputs()[0].name: inp})
        if len(outs) >= 2:
            kx = np.argmax(outs[0][0], axis=-1) / 2.0
            ky = np.argmax(outs[1][0], axis=-1) / 2.0
            px = (kx / iw * W).astype(int)
            py = (ky / ih * H).astype(int)
            n = px.shape[0]
            for (a, b) in connections:
                if a < n and b < n:
                    cv2.line(draw, (px[a], py[a]), (px[b], py[b]), color, 2)
            for i in range(n):
                cv2.circle(draw, (px[i], py[i]), 4, (255, 255, 255), -1)
                cv2.circle(draw, (px[i], py[i]), 3, color, -1)
    except Exception as e:
        cv2.putText(draw, f"pose:{str(e)[:30]}", (8, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 255), 1)
    return draw

_MODE_PROCS = {
    "objects": _proc_objects,
    "segment": _proc_segment,
    "face":    _proc_face,
    "hand":    _proc_hand,
    "body":    _proc_body,
}
_DRAW_ORDER = ["segment", "objects", "face", "body", "hand"]

# ── Persistent MJPEG generator (reads _ACTIVE_MODES live every frame) ────────
def _mjpeg_generator():
    """True real-time pipeline:
    - Thread A: captures camera frames as fast as possible (no inference blocking)
    - Thread B: runs AI inference on latest frame in parallel
    - Generator: streams latest processed frame at display speed
    Mode changes take effect on the very next inference cycle (no restart).
    """
    global _VISION_CAP, _VISION_ACTIVE
    import cv2, queue, threading

    stop_event = threading.Event()
    raw_q  = queue.Queue(maxsize=1)   # latest raw frame (drop old if not consumed)
    proc_q = queue.Queue(maxsize=1)   # latest annotated frame

    # ── Thread A: camera capture ──────────────────────────────────────────────
    def _capture():
        global _VISION_CAP
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        _VISION_CAP = cap
        if not cap.isOpened():
            stop_event.set()
            _VISION_CAP = None
            return
        try:
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                # Drop old frame so inference always gets the freshest one
                try:
                    raw_q.get_nowait()
                except queue.Empty:
                    pass
                raw_q.put(frame)
        finally:
            cap.release()
            _VISION_CAP = None
            stop_event.set()

    # ── Thread B: inference ───────────────────────────────────────────────────
    def _infer():
        while not stop_event.is_set():
            try:
                frame = raw_q.get(timeout=0.05)
            except queue.Empty:
                continue
            current_modes = set(_ACTIVE_MODES)
            draw = frame.copy()
            
            if current_modes:
                # ⚡ [PARALLEL_INFERENCE]: Run all active modes concurrently
                futures = {}
                for m in _DRAW_ORDER:
                    if m in current_modes and m in _MODE_PROCS:
                        # Some modes (like segment/objects) might want the raw frame or the shared draw.
                        # For most, we pass raw frame and they return annotations.
                        futures[m] = _VISION_EXECUTOR.submit(_MODE_PROCS[m], frame, frame.copy())
                
                # Combine annotations back to draw
                for m in _DRAW_ORDER:
                    if m in futures:
                        try:
                            # 🛡️ [FUSE_LOGIC]: Blend the result back to the main draw
                            # Note: Each _proc_ returns a 'draw' with its own annotations.
                            res_draw = futures[m].result(timeout=0.5)
                            
                            # Simple blending: for pose/face/objects it's mostly transparent except annotations
                            # For segmentation it's a full mask.
                            # We use a bitwise or a simple replacement for regions that changed.
                            # For simplicity and speed, we'll use a mask-based approach if needed, 
                            # but most _proc functions draw directly on the frame they were given.
                            # We'll optimize by having each tool return ONLY the delta if we were fancy, 
                            # but for now, we'll just apply them sequentially to 'draw'.
                            # Wait, if they run in parallel, they can't all write to the same 'draw' without locks.
                            # So we have them work on copies and then merge.
                            
                            if m == "segment":
                                # Segment is heavy, blend it first
                                draw = cv2.addWeighted(draw, 0.7, res_draw, 0.3, 0)
                            else:
                                # For others, just copy the pixels that are different (simple heuristic)
                                diff = cv2.absdiff(frame, res_draw)
                                mask = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) > 1
                                draw[mask] = res_draw[mask]
                        except Exception:
                            pass
                
                import cv2 as _cv2
                label = " | ".join(m.upper() for m in _DRAW_ORDER if m in current_modes)
                _cv2.putText(draw, label, (8, draw.shape[0] - 8),
                             _cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
            
            # Always replace old result with newest
            try:
                proc_q.get_nowait()
            except queue.Empty:
                pass
            proc_q.put(draw)

    t_cap  = threading.Thread(target=_capture, daemon=True)
    t_inf  = threading.Thread(target=_infer,   daemon=True)
    t_cap.start()
    t_inf.start()

    last_frame = None
    fps_start = time.time()
    frames_sent = 0
    
    try:
        while _VISION_ACTIVE and not stop_event.is_set():
            try:
                last_frame = proc_q.get(timeout=0.1)
            except queue.Empty:
                if last_frame is None:
                    continue  # not ready yet, wait

            if last_frame is not None:
                # 📈 [TELEMETRY_HUD]: Inject FPS into the stream
                frames_sent += 1
                elapsed = time.time() - fps_start
                if elapsed > 1.0:
                    fps = frames_sent / elapsed
                    frames_sent = 0
                    fps_start = time.time()
                else:
                    fps = frames_sent / max(elapsed, 0.01)

                hud = last_frame.copy()
                cv2.putText(hud, f"FPS: {fps:.1f}", (hud.shape[1]-80, 20), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                ret, buf = cv2.imencode(".jpg", hud, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if ret:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                           + buf.tobytes() + b"\r\n")
    finally:
        stop_event.set()
        t_cap.join(timeout=2)
        t_inf.join(timeout=2)

_last_annotations: list = []
  # unused but kept for future overlay persistence



# ── Vision API endpoints ──────────────────────────────────────────────────────

@app.get("/api/vision/stream")
async def vision_stream(modes: str = "objects"):
    """Persistent MJPEG stream. Initial modes = comma-separated. Change modes live via POST /api/vision/modes."""
    from fastapi.concurrency import iterate_in_threadpool
    global _VISION_ACTIVE, _ACTIVE_MODES

    try:
        import cv2  # noqa
    except ImportError:
        raise HTTPException(status_code=500, detail="opencv-python not installed: pip install opencv-python")

    valid = set(_MODE_PROCS.keys())
    req_modes = {m.strip() for m in modes.split(",") if m.strip() in valid}
    if not req_modes:
        req_modes = {"objects"}

    _ACTIVE_MODES = req_modes
    _VISION_ACTIVE = True

    async def async_gen():
        async for chunk in iterate_in_threadpool(_mjpeg_generator()):
            if not _VISION_ACTIVE:
                break
            yield chunk

    return StreamingResponse(
        async_gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/vision/modes")
async def update_vision_modes(request: Request):
    """Hot-swap active modes without restarting the stream. Body: {modes: ['objects','face',...]}"""
    global _ACTIVE_MODES
    try:
        body = await request.json()
        modes = body.get("modes", [])
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON with 'modes' list")
    valid = set(_MODE_PROCS.keys())
    _ACTIVE_MODES = {m for m in modes if m in valid}
    return {"status": "ok", "active_modes": list(_ACTIVE_MODES)}


@app.post("/api/vision/stop")
def vision_stop():
    """Stop the stream and release the camera."""
    global _VISION_ACTIVE, _VISION_CAP
    _VISION_ACTIVE = False
    if _VISION_CAP is not None:
        try:
            _VISION_CAP.release()
        except Exception:
            pass
        _VISION_CAP = None
    return {"status": "stopped"}


@app.get("/api/vision/status")
def vision_status():
    """Return current vision stream + model status."""
    return {
        "active": _VISION_ACTIVE,
        "camera_open": _VISION_CAP is not None,
        "active_modes": list(_ACTIVE_MODES),
        "models_ready": _MODELS_READY,
        "models_loaded": {
            "yolo_detect":  _VISION_MODEL is not None,
            "yolo_seg":     _VISION_SEG_MODEL is not None,
            "face_cascade": _FACE_CASCADE is not None,
            "onnx":         list(_ONNX_SESSIONS.keys()),
        },
    }


@app.get("/api/todo")
def get_todo_endpoint():
    todo_path = os.path.abspath(os.path.join(_ROOT, "workspace", "todo.md"))
    if not os.path.exists(todo_path):
        return {"content": "", "exists": False}
    try:
        with open(todo_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "exists": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read todo.md: {e}")


@app.post("/api/todo")
async def save_todo_endpoint(request: Request):
    data = await request.json()
    content = str(data.get("content", ""))
    session_id = safe_session_id(data.get("session_id", "default"))
    turn_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("turn_id", "")).strip())[:120]
    
    try:
        write_workspace_todo_plan(content)
        
        # Parse it to update work events
        plan = parse_todo_markdown(content)
        if plan:
            sid = safe_session_id(session_id)
            events_file = work_events_path(sid)
            
            # Read non-todo events
            non_todo_events = []
            if os.path.exists(events_file):
                with open(events_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            evt = json.loads(line)
                            if isinstance(evt, dict) and evt.get("kind") not in ("todo", "planning_artifact") and evt.get("role") != "planning_artifact":
                                non_todo_events.append(evt)
                        except Exception:
                            continue
                            
            # Clear file and write non-todo events
            with open(events_file, "w", encoding="utf-8") as f:
                for evt in non_todo_events:
                    f.write(json.dumps(evt, ensure_ascii=False) + "\n")
                    
            # Add planning_artifact event
            todo_rel_path = os.path.relpath(os.path.join(_ROOT, "workspace", "todo.md"), _ROOT)
            task_text = plan[0].get("task", "Agent Workspace Plan") if plan else "Agent Workspace Plan"
            append_work_event(sid, {
                "kind": "file",
                "type": "file",
                "action": "Edit file",
                "title": "todo.md",
                "task": task_text,
                "target": todo_rel_path,
                "path": todo_rel_path,
                "preview": content,
                "status": "done",
                "turn_id": turn_id,
                "phase": f"Phase 1: {plan[0].get('title', 'Plan')}" if plan else "Phase 1: Plan",
                "phase_index": 1,
                "role": "planning_artifact",
            })
            
            # Recreate todo events
            for index, item in enumerate(plan, start=1):
                title = item.get("title", f"Phase {index}")
                items = item.get("items", [])
                checked = item.get("checked_items", [])
                status = "done" if len(checked) >= len(items) and len(items) > 0 else "running" if index == 1 else "pending"
                append_work_event(sid, {
                    "kind": "todo",
                    "type": "todo",
                    "action": title,
                    "title": title,
                    "task": task_text,
                    "target": title,
                    "items": items,
                    "checked_items": checked,
                    "status": item.get("status", status),
                    "turn_id": turn_id,
                    "phase": f"Phase {index}: {title}",
                    "phase_index": index,
                })
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save and parse todo.md: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
