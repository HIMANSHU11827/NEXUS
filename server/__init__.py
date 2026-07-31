"""
Standalone HTTP API server for NEXUS AI.
Designed for the GUI and external clients.
No vision models, no dashboard bloat — just the chat API.
"""

import asyncio
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from nexus.events import CanonicalEvent
from nexus.run_context import list_run_contexts, load_run_context
from nexus.runtime import (
    build_chat_request,
    safe_session_id as runtime_safe_session_id,
    session_file_path as runtime_session_file_path,
)
from orchestrators.loop import NexusLoop

try:
    import yaml
except Exception:  # pragma: no cover - handled at request time
    yaml = None

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ROOT)  # One level up from server/ to project root
# Run-context storage root. Kept as a separate, monkeypatchable variable so the
# test suite can redirect durable run storage to a temp dir without perturbing
# the rest of the app's project-root derivation.
_RUN_ROOT = _PROJECT_ROOT
_LOOPS: Dict[str, NexusLoop] = {}
_MAX_LOOPS = 20  # Prevent unbounded memory growth
_SESSION_DIR = os.path.join(_PROJECT_ROOT, "logs", "sessions")
_WORK_EVENTS_DIR = os.path.join(_PROJECT_ROOT, "workspace", "work_events")
_WORK_EVENT_SEQUENCE_LOCK = threading.Lock()
_WORK_EVENT_SEQUENCES: Dict[str, int] = {}
# Bounded-retention + cache state for the canonical work-event log. These were
# previously only implemented in the parallel gui/api.py app, which meant the
# server that actually runs in production had an unbounded, uncached log.
_WORK_EVENT_APPEND_LOCK = threading.RLock()
_WORK_EVENT_CACHE_LOCK = threading.RLock()
_WORK_EVENT_CACHE: Dict[str, Tuple[Tuple[int, int], List[Dict[str, Any]], int]] = {}
_WORK_EVENT_MAX_RECORDS = max(100, int(os.environ.get("NEXUS_WORK_EVENT_MAX_RECORDS", "10000")))
_WORK_EVENT_MAX_BYTES = max(1024 * 1024, int(os.environ.get("NEXUS_WORK_EVENT_MAX_BYTES", str(50 * 1024 * 1024))))
_THREAD_LOCAL = threading.local()
_TASKS_PATH = os.path.join(_ROOT, "logs", "tasks.json")
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "nexus_config.yaml")
_CLAUDE_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, ".claude", "settings.json")
_RUNTIME_SETTINGS = {
    "model": "",
    "provider": "",
    "mode": "auto",
    "sandbox_tier": "normal",
    "permission_allowlist": [],
    "agent": "",
    "goal": "",
    "additional_dirs": [],
}
_RUNTIME_FEATURE_DEFAULTS = {
    "hive": True,
    "evolution": True,
    "scheduler": True,
    "reminders": True,
    "health": True,
}

import subprocess

_VOICE_PROCESS: Optional[subprocess.Popen] = None
_VOICE_MODE = "off"
_VOICE_STARTED_AT = 0.0
_VOICE_LOG_PATH = os.path.join(_PROJECT_ROOT, "logs", "voice-runtime.log")

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Join response-detached learning tasks before asyncio tears down."""
    yield
    await _drain_loop_finalizers(tuple(_LOOPS.values()))


async def _drain_loop_finalizers(loops) -> None:
    """Await async loop closers while tolerating synchronous test/legacy doubles."""
    pending = []
    for loop in loops:
        close = getattr(loop, "aclose", None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            pending.append(result)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _close_loop(loop: NexusLoop) -> None:
    """Close an evicted loop without assuming every legacy loop is async."""
    close = getattr(loop, "aclose", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _log_close_failure(task: asyncio.Task) -> None:
    try:
        task.result()
    except Exception:
        logger.warning("Failed to close evicted loop", exc_info=True)


def _schedule_loop_close(loop: NexusLoop) -> None:
    """Schedule async cleanup from async routes, with a sync-route fallback."""
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_close_loop(loop))
        except Exception:
            logger.warning("Failed to close evicted loop", exc_info=True)
        return

    task = running_loop.create_task(_close_loop(loop))
    task.add_done_callback(_log_close_failure)


app = FastAPI(title="NEXUS AI API", version="2.1.0", lifespan=_app_lifespan)

# ── Session middleware (signed cookies) ─────────────────────────────
from starlette.middleware.sessions import SessionMiddleware

from authentication import _SESSION_SECRET as _session_secret

app.add_middleware(SessionMiddleware, secret_key=_session_secret, max_age=86400)

# ── CORS middleware ─────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

_DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _cors_origins() -> list:
    """Explicit CORS allowlist. Wildcard is refused while credentials are on."""
    raw = os.environ.get("NEXUS_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    safe = [o for o in origins if o != "*"]
    if len(safe) != len(origins):
        logger.warning(
            "NEXUS_CORS_ORIGINS contained '*'; wildcard is ignored because "
            "allow_credentials=True. Falling back to the explicit allowlist."
        )
    return safe or list(_DEFAULT_CORS_ORIGINS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# ── Auth middleware ─────────────────────────────────────────────────
from authentication import AuthUser, check_auth

_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", "com1", "com2", "com3", "com4",
    "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
    "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"})

_AUTH_SKIP_PATHS = frozenset({
    "/api/health", "/api/files/list", "/api/auth/login", "/api/auth/callback",
    "/api/auth/token", "/api/logout", "/api/auth/status",
    "/api/state", "/api/version",
    "/docs", "/openapi.json", "/redoc",
    "/api/features",
})

if os.environ.get("NEXUS_PUBLIC_OPENAI_COMPAT", "false").lower() == "true":
    _AUTH_SKIP_PATHS = frozenset((*_AUTH_SKIP_PATHS, "/v1/models", "/v1/chat/completions"))


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_SKIP_PATHS or path.startswith(("/docs/", "/openapi/", "/redoc/")):
        return await call_next(request)

    # NEXUS_ALLOW_LOCAL_ANON is an explicit opt-in used by local/test clients
    # (and the pytest suite via TestClient, whose peer host is the literal
    # string "testclient" rather than a real loopback address). It is OFF by
    # default and MUST stay that way; anonymous access is only ever granted
    # when an operator deliberately sets the flag.
    if os.environ.get("NEXUS_ALLOW_LOCAL_ANON", "false").lower() == "true":
        request.state.user = AuthUser(provider="local", sub="dashboard", name="Local User")
        return await call_next(request)

    user = check_auth(request)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    request.state.user = user
    return await call_next(request)


# ── Auth routes ─────────────────────────────────────────────────────

@app.get("/api/auth/login")
async def auth_login(provider: str = "token", redirect: str = ""):
    """Initiate login.

    - ``provider=token``: Returns auth status (use ``Authorization`` header).
    - ``provider=google|github``: Redirects to OAuth provider.
    """
    if provider == "token":
        return {"status": "ok", "message": "Use Authorization: Bearer <token> header"}

    from authentication import OAUTH_PROVIDERS, get_oauth_authorize_url

    oauth = OAUTH_PROVIDERS.get(provider)
    if not oauth:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    base_redirect = redirect or f"{os.environ.get('NEXUS_API_BASE', 'http://127.0.0.1:8000')}/api/auth/callback"
    redirect_uri = f"{base_redirect}?provider={provider}"
    url, state = get_oauth_authorize_url(provider, redirect_uri)
    return RedirectResponse(url=url)


@app.get("/api/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", provider: str = ""):
    """OAuth callback handler — exchange code for user info."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    _provider = provider or (state.split(":", 1)[0] if ":" in state else "")
    if not _provider or _provider not in ("google", "github"):
        raise HTTPException(status_code=400, detail="Invalid provider")

    base_redirect = f"{os.environ.get('NEXUS_API_BASE', 'http://127.0.0.1:8000')}/api/auth/callback"
    redirect_uri = f"{base_redirect}?provider={_provider}"

    from authentication import handle_oauth_callback
    result = await handle_oauth_callback(_provider, code, state, redirect_uri)
    if not result.success or not result.user:
        raise HTTPException(status_code=401, detail=result.error)

    request.session["user"] = result.user.to_dict()
    return RedirectResponse(url=os.environ.get("NEXUS_DASHBOARD_URL", "http://127.0.0.1:5173"))


@app.post("/api/auth/token")
async def auth_token(request: Request):
    """Exchange a token for a session cookie (for non-OAuth login).

    Body: ``{"token": "..."}`` or use ``Authorization: Bearer <token>`` header.
    """
    from authentication import validate_dashboard_token

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    token = body.get("token", "") or request.headers.get("Authorization", "").replace("Bearer ", "")

    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    if not validate_dashboard_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = AuthUser(provider="token", sub="dashboard", name="Token User")
    request.session["user"] = user.to_dict()
    return {"status": "ok", "user": user.to_dict()}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    """Return current auth status and user info."""

    user_data = None
    session = getattr(request, "session", None)
    if session and "user" in session:
        user_data = session["user"]

    if not user_data:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from authentication import validate_dashboard_token
            token = auth[7:]
            if validate_dashboard_token(token):
                user_data = {"provider": "token", "sub": "dashboard", "name": "Token User"}

    return {
        "authenticated": user_data is not None,
        "user": user_data,
        "token_configured": bool(os.environ.get("NEXUS_DASHBOARD_TOKEN", "")),
        "oauth_providers": list(os.environ.get("NEXUS_GOOGLE_CLIENT_ID", "") and ["google"] or [])
        + list(os.environ.get("NEXUS_GITHUB_CLIENT_ID", "") and ["github"] or []),
    }


@app.post("/api/logout")
async def auth_logout(request: Request):
    """Logout — clear the session."""
    request.session.clear()
    return {"status": "ok", "message": "Logged out"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}" if str(exc) else "Internal server error"}
    )


def _trim_loops():
    """Evict oldest loop sessions if over limit."""
    if len(_LOOPS) > _MAX_LOOPS:
        # Evict oldest (arbitrary order since dict preserves insertion)
        keys = list(_LOOPS.keys())
        for k in keys[:len(keys) - _MAX_LOOPS]:
            try:
                evicted = _LOOPS.pop(k)
            except KeyError:
                logger.warning("server/__init__.py suppressed error", exc_info=True)
            else:
                _schedule_loop_close(evicted)


def safe_session_id(session_id: str) -> str:
    return runtime_safe_session_id(session_id)


def session_file_path(session_id: str, suffix: str = ".json") -> str:
    try:
        return runtime_session_file_path(_SESSION_DIR, session_id, suffix)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id")


def work_events_path(session_id: str) -> str:
    sid = safe_session_id(session_id)
    os.makedirs(_WORK_EVENTS_DIR, exist_ok=True)
    return os.path.join(_WORK_EVENTS_DIR, f"{sid}.jsonl")


def _next_work_event_sequence(path: str) -> int:
    """Return a restart-safe monotonic sequence for one persisted work stream."""
    with _WORK_EVENT_SEQUENCE_LOCK:
        if path not in _WORK_EVENT_SEQUENCES:
            last = 0
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            event = json.loads(line)
                            last = max(last, int(event.get("sequence") or 0))
                        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                            continue
            except FileNotFoundError:
                pass
            _WORK_EVENT_SEQUENCES[path] = last
        _WORK_EVENT_SEQUENCES[path] += 1
        return _WORK_EVENT_SEQUENCES[path]


# ----------------------------------------------------------------------
# Canonical work-event layer (ported from the retired gui/api.py app so the
# server that actually runs owns ONE implementation: bounded retention,
# signature-cached reads, canonical envelopes, cursor replay, live sink).
# ----------------------------------------------------------------------

def _work_event_log_signature(path: str) -> Tuple[int, int]:
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return 0, 0


def _scan_work_event_log(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """Scan with bounded memory, retaining the tail plus older active lifecycles."""
    tail = deque(maxlen=_WORK_EVENT_MAX_RECORDS)
    active: Dict[str, Dict[str, Any]] = {}
    record_count = 0
    if not os.path.exists(path):
        return [], 0
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            record_count += 1
            tail.append(event)
            event_id = str(event.get("event_id") or event.get("id") or "")
            if not event_id:
                continue
            status = str(event.get("status") or "").lower()
            if status in {"pending", "running", "queued", "started", "in_progress"}:
                active[event_id] = event
            else:
                active.pop(event_id, None)
    retained = list(tail)
    retained_ids = {str(event.get("event_id") or event.get("id") or "") for event in retained}
    retained.extend(event for event_id, event in active.items() if event_id not in retained_ids)
    retained.sort(key=lambda event: int(event.get("sequence") or 0))
    return retained, record_count


def _cached_work_events(path: str) -> Tuple[List[Dict[str, Any]], int]:
    signature = _work_event_log_signature(path)
    with _WORK_EVENT_CACHE_LOCK:
        cached = _WORK_EVENT_CACHE.get(path)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
    events, count = _scan_work_event_log(path)
    with _WORK_EVENT_CACHE_LOCK:
        _WORK_EVENT_CACHE[path] = (signature, events, count)
    return events, count


def _invalidate_work_event_cache(path: str) -> None:
    with _WORK_EVENT_CACHE_LOCK:
        _WORK_EVENT_CACHE.pop(path, None)


def _compact_work_event_log_if_needed(path: str) -> None:
    """Atomically compact oversized JSONL while keeping sequence cursors monotonic."""
    events, record_count = _cached_work_events(path)
    current_size = _work_event_log_signature(path)[1]
    if record_count <= _WORK_EVENT_MAX_RECORDS and current_size <= _WORK_EVENT_MAX_BYTES:
        return
    encoded = [json.dumps(event, ensure_ascii=False) + "\n" for event in events]
    # Active lifecycle evidence is lossless even if it alone exceeds a soft
    # retention limit; avoid rewriting the same irreducible log every append.
    if sum(len(line.encode("utf-8")) for line in encoded) >= current_size:
        return
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    _invalidate_work_event_cache(path)


def safe_workspace_read_path(raw_path: str) -> str:
    value = str(raw_path or "").strip().strip('"').strip("'")
    if not value:
        raise HTTPException(status_code=400, detail="Path is required")
    if not os.path.isabs(value):
        value = os.path.join(_PROJECT_ROOT, value)
    path = os.path.abspath(value)
    root = os.path.abspath(_PROJECT_ROOT)
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(status_code=400, detail="Path is outside the NEXUS workspace")
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return path


def write_workspace_todo_plan(content: str) -> str:
    """Persist the visible agent plan as a real workspace file (atomic)."""
    workspace_dir = os.path.join(_PROJECT_ROOT, "workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    todo_path = os.path.abspath(os.path.join(workspace_dir, "todo.md"))
    if os.path.commonpath([os.path.abspath(workspace_dir), todo_path]) != os.path.abspath(workspace_dir):
        raise HTTPException(status_code=400, detail="Invalid todo path")
    temp_path = f"{todo_path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_path, todo_path)
    return os.path.relpath(todo_path, _PROJECT_ROOT)



# ── Plan / todo workflow (ported from the canonical gui.api implementation) ──
def clear_workspace_todo_plan() -> None:
    try:
        todo_path = os.path.abspath(os.path.join(_PROJECT_ROOT, "workspace", "todo.md"))
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

    todo_path = os.path.abspath(os.path.join(_PROJECT_ROOT, "workspace", "todo.md"))
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


def refresh_provider_runtime() -> str:
    """Reload provider.yml and return the canonical default provider."""
    try:
        from config.config_loader import NexusConfigLoader
        loader = NexusConfigLoader()
        loader.reload()
        provider_cfg = loader.get("provider", {})
        default_provider = ""
        if isinstance(provider_cfg, dict):
            default_provider = str(provider_cfg.get("default_provider") or "").strip()
        try:
            from providers.factory import NexusProviderFactory
            factory = NexusProviderFactory()
            if hasattr(factory, "loader") and hasattr(factory.loader, "reload"):
                factory.loader.reload()
            factory._provider = None
            if default_provider:
                factory.name = default_provider
        except Exception:
            logger.debug("Provider factory refresh skipped", exc_info=True)
        return default_provider or loader.get_system("provider_name", "openrouter")
    except Exception:
        logger.warning("Provider runtime refresh failed", exc_info=True)
        return "openrouter"


def update_todo_file_and_states(session_id: str, new_event: Dict[str, Any], turn_id: str = "") -> List[Dict[str, Any]]:
    if new_event.get("role") == "planning_artifact" or new_event.get("kind") == "todo":
        return []
    sid = safe_session_id(session_id)
    events = list_work_events(sid, limit=1000, turn_id=turn_id)
    if turn_id:
        events = [e for e in events if str(e.get("turn_id", "")) == turn_id]
    todo_events = [e for e in events if e.get("kind") == "todo" and e.get("phase_index") is not None]
    if not todo_events:
        return []
    
    # Sort todo events by phase_index
    todo_events.sort(key=lambda x: int(x.get("phase_index") or 0))
    
    kind = str(new_event.get("kind") or "").lower()
    status = str(new_event.get("status") or "").lower()
    if status == "success":
        status = "done"
    elif status == "failed":
        status = "error"
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
    elif (
        "file" in raw_kind
        or "file" in raw_action
        or "file" in raw_tool
        or raw_kind in {"reading", "creating", "modifying", "deleting"}
        or raw_tool in {"reading", "creating", "modifying", "deleting"}
        or event.get("path")
    ):
        kind = "file"
    elif "skill" in raw_kind:
        kind = "skill"
    elif "plugin" in raw_kind:
        kind = "plugin"
    elif "provider" in raw_kind:
        kind = "provider"
    elif any(token in raw_kind for token in ("hive", "subagent", "agent", "worker")):
        kind = "hive"
    elif "todo" in raw_kind:
        kind = "todo"
    else:
        kind = raw_kind or "tool"

    action = str(event.get("action") or event.get("title") or "").strip()
    if not action:
        if kind == "file":
            file_tool = raw_tool or raw_kind
            if file_tool == "reading":
                action = "Read file"
            elif file_tool == "creating":
                action = "Create file"
            elif file_tool == "modifying":
                action = "Edit file"
            elif file_tool == "deleting":
                action = "Delete file"
            elif any(token in raw_action for token in ("delete", "remove")):
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
            event["path"] = os.path.relpath(file_path, _PROJECT_ROOT)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                event["preview"] = f.read(20000)
        except Exception as exc:
            event["preview_error"] = str(exc)
    os.makedirs(_WORK_EVENTS_DIR, exist_ok=True)
    path = work_events_path(session_id)
    with _WORK_EVENT_APPEND_LOCK:
        if event.get("sequence") is not None:
            event["source_sequence"] = event["sequence"]
        sequence = _next_work_event_sequence(path)
        canonical = CanonicalEvent.from_work_event(event, event["session_id"], sequence).to_dict()
        event["legacy_type"] = event.get("type")
        event["legacy_status"] = event.get("status")
        event.update(canonical)
        # Compatibility aliases remain during the adapter migration; all new
        # records still persist the complete canonical envelope above.
        event["id"] = event["event_id"]
        event["session_id"] = event["conversation_id"]
        event["created_at"] = event["timestamp"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        _invalidate_work_event_cache(path)
        _compact_work_event_log_if_needed(path)
        
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


def replay_work_events_after(session_id: str, after_sequence: int, limit: int = 200) -> List[Dict[str, Any]]:
    """Replay the append-only canonical log without lifecycle-state dedupe."""
    events: List[Dict[str, Any]] = []
    path = work_events_path(session_id)
    raw_events, _ = _cached_work_events(path)
    for event in raw_events:
        if str(event.get("visibility", "")).lower() == "internal":
            continue
        if int(event.get("sequence") or 0) > after_sequence:
            events.append(event)
            if len(events) >= max(1, min(limit, 1000)):
                break
    return events[:max(1, min(limit, 1000))]


def bind_live_work_event_sink(loop: NexusLoop, session_id: str, turn_id: str, out_queue) -> tuple[Any, Any]:
    """Multiplex structured loop events into persistence and the active stream."""
    previous = loop.work_event_sink

    def live_sink(payload: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(payload)
        if turn_id:
            enriched.setdefault("turn_id", turn_id)
        event = append_work_event(session_id, enriched)
        if str(event.get("visibility") or "public").lower() == "public":
            out_queue.put(("event", event))
        return event

    loop.work_event_sink = live_sink
    return previous, live_sink


def encode_chat_stream_frame(event: str, payload: Any, *, legacy: bool = False) -> str:
    """Serialize one chat transport record as valid SSE (or explicit legacy raw)."""
    if legacy:
        if event == "message":
            return str(payload.get("content", "")) if isinstance(payload, dict) else str(payload)
        if event == "work_event":
            item = payload.get("event", payload) if isinstance(payload, dict) else payload
            return f"[NEXUS_ACTIVITY]: {json.dumps(item, ensure_ascii=False)}\n"
        return ""
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _append_work_event(session_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    sid = safe_session_id(session_id)
    payload = dict(event)
    payload.setdefault("session_id", sid)
    path = work_events_path(sid)
    if not payload.get("sequence"):
        payload["sequence"] = _next_work_event_sequence(path)
    else:
        try:
            sequence = int(payload.get("sequence") or 0)
            with _WORK_EVENT_SEQUENCE_LOCK:
                _WORK_EVENT_SEQUENCES[path] = max(_WORK_EVENT_SEQUENCES.get(path, 0), sequence)
        except (TypeError, ValueError):
            payload["sequence"] = _next_work_event_sequence(path)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def _is_private_diagnostic_event(event: Dict[str, Any]) -> bool:
    """Mirror of the frontend's isPrivateDiagnosticEvent.

    Private grounding and internal self-diagnostics (prompt files, the critical
    preventive vaccine, tool-safety audits, etc.) are never public evidence and
    must never replay into the visible timeline, even if a surface forgets to
    mark them visibility='internal'. Keeping the rule server-side means the
    backend work-event API is safe on its own, not only when rendered by a
    frontend that happens to apply the filter.
    """
    haystack = " ".join(
        str(event.get(k) or "")
        for k in ("target", "path", "title", "summary", "query", "tool", "action")
    )
    if str(event.get("stage") or "").lower() == "grounding" and "prompt" in haystack.lower():
        return True
    patterns = (
        "prompt_files", "critical preventive vaccine", "tool safety audit",
        "agent tools", "latest tool results", "tool results accepted",
    )
    return any(p in haystack.lower() for p in patterns)


def list_work_events(session_id: str, limit: int = 200, turn_id: str = "", after_sequence: int = 0):
    """Collapse a work-event log into current timeline state.

    Each event id appears once, holding its LATEST persisted state, at the
    position where it was FIRST seen. This is what the GUI timeline renders:
    a running command that later completes must update in place rather than
    appear twice or jump to the end. Reads go through the signature cache so
    repeated polling does not rescan the whole log.
    """
    path = work_events_path(session_id)
    raw_events, _ = _cached_work_events(path)

    order: List[str] = []
    latest: Dict[str, Dict[str, Any]] = {}
    anonymous: List[Dict[str, Any]] = []
    for event in raw_events:
        if str(event.get("visibility") or "public").lower() == "internal":
            continue
        if _is_private_diagnostic_event(event):
            continue
        try:
            sequence = int(event.get("sequence") or 0)
        except (TypeError, ValueError):
            sequence = 0
        if after_sequence and sequence <= after_sequence:
            continue
        if turn_id and str(event.get("turn_id") or event.get("run_id") or "") != str(turn_id):
            continue
        event_id = str(event.get("event_id") or event.get("id") or "")
        if not event_id:
            anonymous.append(event)
            continue
        if event_id not in latest:
            order.append(event_id)
        latest[event_id] = event

    events = [latest[event_id] for event_id in order] + anonymous
    return events[-max(1, min(int(limit or 200), 1000)):]


def work_event_run_summary(session_id: str, run_id: str) -> Dict[str, Any]:
    events = list_work_events(session_id, limit=1000, turn_id=run_id)
    statuses: Dict[str, int] = {}
    kinds: Dict[str, int] = {}
    last_sequence = 0
    terminal_event = ""
    for event in events:
        status = str(event.get("status") or "unknown")
        kind = str(event.get("kind") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        kinds[kind] = kinds.get(kind, 0) + 1
        try:
            last_sequence = max(last_sequence, int(event.get("sequence") or 0))
        except (TypeError, ValueError):
            pass
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type.startswith("run.") and status in {"success", "failed", "cancelled"}:
            terminal_event = event_type
    return {
        "event_count": len(events),
        "last_sequence": last_sequence,
        "statuses": statuses,
        "kinds": kinds,
        "terminal_event": terminal_event,
    }


def get_loop(session_id: str = "default") -> NexusLoop:
    sid = safe_session_id(session_id)
    if sid not in _LOOPS:
        loop = NexusLoop(root_dir=_PROJECT_ROOT)
        try:
            loop.load_memory(sid)
        except Exception as e:
            logger.warning("get_loop: failed to load memory for session %s: %s", sid, e)
        apply_runtime_settings(loop)
        # Every loop persists its structured work events by default. Without a
        # baseline sink, activity produced outside an active /api/chat stream
        # (background runs, gateway turns, resumed work) was silently dropped
        # and never reached the timeline or the durable log.
        def default_sink(payload: Dict[str, Any], _sid: str = sid) -> Dict[str, Any]:
            return append_work_event(_sid, payload)

        loop.work_event_sink = default_sink
        _LOOPS[sid] = loop
        _trim_loops()
    return _LOOPS[sid]


def set_active_session(session_id: str, source: str = "cli-api") -> None:
    try:
        from utils.session_bus import set_active_session_id
        set_active_session_id(_PROJECT_ROOT, session_id, source=source)
    except Exception as e:
        logger.warning("set_active_session: failed for %s: %s", session_id, e)


def _normalize_permission_mode(mode: str) -> str:
    aliases = {
        "": "auto",
        "default": "ask",
        "approve": "ask",
        "approval": "ask",
        "askall": "ask",
        "ask_all": "ask",
        "ask-once": "ask",
        "ask_once": "ask",
        "once": "ask",
        "bypass": "all",
        "dontask": "all",
        "dont_ask": "all",
        "noask": "all",
        "allow": "allowlist",
        "allowed": "allowlist",
        "allow-list": "allowlist",
        "whitelist": "allowlist",
        "preauth": "allowlist",
        "pre_authorized": "allowlist",
        "checklist": "allowlist",
        "acceptedits": "auto",
        "accept": "auto",
        "auto_pilot": "auto",
        "autopilot": "auto",
    }
    normalized = str(mode or "").strip().lower().replace(" ", "_")
    return aliases.get(normalized, normalized)


def _normalize_sandbox_tier(tier: str) -> str:
    aliases = {
        "": "no_sandbox",
        "none": "no_sandbox",
        "off": "no_sandbox",
        "no": "no_sandbox",
        "no-sandbox": "no_sandbox",
        "nosandbox": "no_sandbox",
        "bypass": "no_sandbox",
        "simple": "normal",
        "safe": "normal",
        "on": "normal",
        "advanced": "docker",
    }
    normalized = str(tier or "").strip().lower().replace(" ", "_")
    return aliases.get(normalized, normalized)


def apply_runtime_settings(loop: NexusLoop) -> None:
    """Apply CLI-selected runtime settings to a loop instance."""
    model = str(_RUNTIME_SETTINGS.get("model") or "").strip()
    provider = str(_RUNTIME_SETTINGS.get("provider") or "").strip()
    mode = _normalize_permission_mode(str(_RUNTIME_SETTINGS.get("mode") or "auto"))
    sandbox_tier = _normalize_sandbox_tier(str(_RUNTIME_SETTINGS.get("sandbox_tier") or "normal"))
    agent = str(_RUNTIME_SETTINGS.get("agent") or "").strip()
    goal = str(_RUNTIME_SETTINGS.get("goal") or "").strip()
    additional_dirs = _RUNTIME_SETTINGS.get("additional_dirs") or []
    allowlist = [str(item).strip() for item in (_RUNTIME_SETTINGS.get("permission_allowlist") or []) if str(item).strip()]

    loop.model = model
    loop.provider_override = provider
    loop.permission_mode = mode
    loop.active_agent = agent
    loop.active_goal = goal
    loop.additional_dirs = [str(item) for item in additional_dirs if str(item).strip()]
    loop.checklist = set(allowlist) or getattr(loop, "checklist", set())

    if provider:
        try:
            loop.brain.set_override(provider)
        except Exception as e:
            logger.warning("apply_runtime_settings: provider override %s failed: %s", provider, e)

    if model:
        try:
            active_provider = getattr(loop.brain.base_router, "provider", None)
            if active_provider is not None and hasattr(active_provider, "model"):
                active_provider.model = model
        except Exception as e:
            logger.warning("apply_runtime_settings: model %s failed: %s", model, e)

    try:
        from permissions import PermissionMode
        from orchestrators.loop import PermissionPolicy
        from sandbox.sandbox_manager import SandboxTier
        mode_map = {
            "auto": PermissionMode.AUTO_PILOT,
            "all": PermissionMode.BYPASS,
            "ask": PermissionMode.APPROVE,
            "allowlist": PermissionMode.PRE_AUTHORIZED,
            "plan": PermissionMode.PLAN,
            "acceptedits": PermissionMode.AUTO_PILOT,
            "accept": PermissionMode.AUTO_PILOT,
            "dontask": PermissionMode.BYPASS,
            "bypass": PermissionMode.BYPASS,
            "approve": PermissionMode.APPROVE,
            "pre_authorized": PermissionMode.PRE_AUTHORIZED,
            "checklist": PermissionMode.PRE_AUTHORIZED,
            "default": PermissionMode.DEFAULT,
        }
        policy_map = {
            "auto": PermissionPolicy.AI_DECIDE,
            "all": PermissionPolicy.AUTO,
            "ask": PermissionPolicy.ASK_ALL,
            "allowlist": PermissionPolicy.CHECKLIST,
            "plan": PermissionPolicy.CHECKLIST,
            "acceptedits": PermissionPolicy.AI_DECIDE,
            "accept": PermissionPolicy.AI_DECIDE,
            "dontask": PermissionPolicy.AUTO,
            "bypass": PermissionPolicy.AUTO,
            "approve": PermissionPolicy.ASK_ALL,
            "pre_authorized": PermissionPolicy.CHECKLIST,
            "checklist": PermissionPolicy.CHECKLIST,
            "default": PermissionPolicy.ASK_ALL,
        }
        loop.policy = policy_map.get(mode, PermissionPolicy.AI_DECIDE)
        loop.permissions.set_mode(mode_map.get(mode, PermissionMode.AUTO))
        loop.permissions._pre_authorized_list = allowlist
        loop.sandbox_tier = SandboxTier(sandbox_tier)
        loop.sandbox.tier = loop.sandbox_tier
    except Exception as e:
        logger.warning("apply_runtime_settings: permission mode %s failed: %s", mode, e)


def _check_gui_terminal_permission(sid: str, turn_id: str, command: str):
    """Evaluate the terminal permission policy for a GUI command-run request.

    Mirrors the canonical gui.api implementation. The GUI terminal surface
    enforces the session's permission mode before handing a command to the
    sandbox, so a restrictive mode (ask / default / allowlist) does not
    silently execute destructive commands. Returns the PermissionSystem result.
    """
    from permissions import PermissionMode, PermissionSystem

    loop = _LOOPS.get(sid)
    mode_name = str(getattr(loop, "permission_mode", "") if loop else "auto").strip().lower() or "auto"
    mode_map = {
        "full_access": PermissionMode.BYPASS,
        "all": PermissionMode.BYPASS,
        "bypass": PermissionMode.BYPASS,
        "dontask": PermissionMode.BYPASS,
        "accept": PermissionMode.AUTO_PILOT,
        "acceptedits": PermissionMode.AUTO_PILOT,
        "auto": PermissionMode.AUTO_PILOT,
        "auto_pilot": PermissionMode.AUTO_PILOT,
        "allowlist": PermissionMode.PRE_AUTHORIZED,
        "pre_authorized": PermissionMode.PRE_AUTHORIZED,
        "checklist": PermissionMode.PRE_AUTHORIZED,
        "approval": PermissionMode.APPROVE,
        "ask": PermissionMode.APPROVE,
        "approve": PermissionMode.APPROVE,
        "default": PermissionMode.DEFAULT,
        "plan": PermissionMode.PLAN,
    }
    permissions = PermissionSystem()
    previous_mode = permissions.mode
    try:
        permissions.set_mode(mode_map.get(mode_name, PermissionMode.AUTO_PILOT))
        return permissions.check(
            "terminal",
            command,
            context={"session_id": sid, "turn_id": turn_id, "surface": "gui"},
        )
    finally:
        permissions.set_mode(previous_mode)


def apply_runtime_to_all_loops() -> None:
    for loop in list(_LOOPS.values()):
        apply_runtime_settings(loop)


def _clear_session_files(session_id: str) -> bool:
    path = session_file_path(session_id)
    meta_path = session_file_path(session_id, ".meta")
    existed = os.path.exists(path) or os.path.exists(meta_path) or session_id in _LOOPS

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
            logger.warning("server:364 _clear_session_files: suppressed error", exc_info=True)
            pass

    return existed


def _require_yaml():
    if yaml is None:
        raise HTTPException(status_code=500, detail="PyYAML is required for config management")


def _load_nexus_config() -> Dict[str, Any]:
    _require_yaml()
    if not os.path.exists(_CONFIG_PATH):
        return {}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="nexus_config.yaml must contain a mapping")
    return data


def _save_nexus_config(config: Dict[str, Any]) -> None:
    _require_yaml()
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    tmp_path = f"{_CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, width=100)
    os.replace(tmp_path, _CONFIG_PATH)


def _load_runtime_preferences() -> None:
    try:
        config = _load_nexus_config()
        runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        if "permission_mode" in runtime:
            _RUNTIME_SETTINGS["mode"] = _normalize_permission_mode(str(runtime.get("permission_mode") or "auto"))
        if "sandbox_tier" in runtime:
            _RUNTIME_SETTINGS["sandbox_tier"] = _normalize_sandbox_tier(str(runtime.get("sandbox_tier") or "normal"))
            os.environ["NEXUS_SANDBOX_TIER"] = str(_RUNTIME_SETTINGS["sandbox_tier"])
        allowlist = runtime.get("permission_allowlist")
        if isinstance(allowlist, list):
            _RUNTIME_SETTINGS["permission_allowlist"] = [str(item).strip() for item in allowlist if str(item).strip()]
    except Exception:
        logger.warning("load_runtime_preferences: failed", exc_info=True)


def _save_runtime_preferences() -> None:
    try:
        config = _load_nexus_config()
        runtime = config.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            config["runtime"] = runtime
        runtime["permission_mode"] = _normalize_permission_mode(_RUNTIME_SETTINGS.get("mode") or "auto")
        runtime["permission_allowlist"] = _RUNTIME_SETTINGS.get("permission_allowlist") or []
        runtime["sandbox_tier"] = _normalize_sandbox_tier(_RUNTIME_SETTINGS.get("sandbox_tier") or "normal")
        _save_nexus_config(config)
    except Exception:
        logger.warning("save_runtime_preferences: failed", exc_info=True)


_load_runtime_preferences()


def _load_claude_settings(strict: bool = False) -> Dict[str, Any]:
    if not os.path.exists(_CLAUDE_SETTINGS_PATH):
        return {}
    try:
        with open(_CLAUDE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        if strict:
            raise HTTPException(status_code=500, detail=f"Cannot edit malformed .claude/settings.json: {exc}")
        return {}


def _save_claude_settings(settings: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_CLAUDE_SETTINGS_PATH), exist_ok=True)
    tmp_path = f"{_CLAUDE_SETTINGS_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp_path, _CLAUDE_SETTINGS_PATH)


def _runtime_features(config: Dict[str, Any]) -> Dict[str, bool]:
    features = config.setdefault("runtime_features", {})
    if not isinstance(features, dict):
        features = {}
        config["runtime_features"] = features
    for key, value in _RUNTIME_FEATURE_DEFAULTS.items():
        features.setdefault(key, value)
    return features


def _list_membership(config: Dict[str, Any], key: str) -> list:
    value = config.setdefault(key, [])
    if not isinstance(value, list):
        value = []
        config[key] = value
    return value


def _set_disabled(config: Dict[str, Any], key: str, name: str, disabled: bool) -> None:
    items = _list_membership(config, key)
    if disabled and name not in items:
        items.append(name)
    if not disabled and name in items:
        items.remove(name)


def _provider_entry(config: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    providers = config.setdefault("providers", {})
    if not isinstance(providers, dict):
        config["providers"] = providers = {}
    for group_name in ("cloud", "local", "self_hosted"):
        group = providers.setdefault(group_name, {})
        if isinstance(group, dict) and provider in group and isinstance(group[provider], dict):
            return group[provider]
    cloud = providers.setdefault("cloud", {})
    if not isinstance(cloud, dict):
        providers["cloud"] = cloud = {}
    cloud[provider] = {"active": True}
    return cloud[provider]


def _flatten_providers(config: Dict[str, Any]) -> list:
    rows = []
    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        return rows
    for group_name, group in providers.items():
        if not isinstance(group, dict):
            continue
        for name, entry in group.items():
            if not isinstance(entry, dict):
                continue
            rows.append({
                "id": name,
                "group": group_name,
                "active": bool(entry.get("active", False)),
                "model": entry.get("model", ""),
                "endpoint": entry.get("endpoint", ""),
            })
    return sorted(rows, key=lambda item: (item["group"], item["id"]))


def _load_tasks() -> Dict[str, dict]:
    if os.path.exists(_TASKS_PATH):
        try:
            with open(_TASKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("_load_tasks: corrupt tasks file (%s), starting fresh", e)
    return {}


def _save_tasks(tasks: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(_TASKS_PATH), exist_ok=True)
    tmp = f"{_TASKS_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)
    os.replace(tmp, _TASKS_PATH)


def _clear_runtime(reason: str) -> Dict[str, Any]:
    count = len(_LOOPS)
    _LOOPS.clear()
    return {"reloaded_loops": count, "reason": reason}


def _parse_config_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    raw = value.strip()
    lowered = raw.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return value


def _set_dotted(config: Dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = [part for part in dotted_path.split(".") if part]
    if not parts:
        raise HTTPException(status_code=400, detail="config path is required")
    current: Dict[str, Any] = config
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = _parse_config_value(value)


def _config_summary() -> Dict[str, Any]:
    config = _load_nexus_config()
    settings = _load_claude_settings()
    disabled_tools = set(_list_membership(config, "disabled_tools"))
    disabled_skills = set(_list_membership(config, "disabled_skills"))
    tools = []
    for name, entry in sorted((config.get("custom_tool_configs") or {}).items()):
        if not isinstance(entry, dict):
            continue
        tools.append({
            "name": name,
            "description": str(entry.get("description", ""))[:120],
            "enabled": bool(entry.get("active", True)) and name not in disabled_tools,
        })
    skills = []
    for name, entry in sorted((config.get("custom_skill_configs") or {}).items()):
        if not isinstance(entry, dict):
            continue
        skills.append({
            "name": name,
            "description": str(entry.get("description", ""))[:120],
            "enabled": bool(entry.get("active", True)) and name not in disabled_skills,
        })
    mcp = []
    for name, entry in sorted((config.get("mcp_servers") or {}).items()):
        if not isinstance(entry, dict):
            continue
        mcp.append({
            "id": name,
            "description": str(entry.get("description", ""))[:120],
            "active": bool(entry.get("active", False)),
            "command": entry.get("command", ""),
        })
    plugins = [
        {"id": pid, "name": pid.split("@")[0], "enabled": bool(enabled)}
        for pid, enabled in sorted((settings.get("enabledPlugins") or {}).items())
    ]
    return {
        "tools": tools,
        "skills": skills,
        "mcp": mcp,
        "plugins": plugins,
        "providers": _flatten_providers(config),
        "features": _runtime_features(config),
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nexus-api"}


@app.get("/api/state")
def get_state():
    """Alias for /api/status — runtime state."""
    return get_status()


@app.get("/api/version")
def get_version():
    return {"version": app.version, "service": "nexus-api"}


@app.get("/api/sessions")
def list_sessions():
    if not os.path.exists(_SESSION_DIR):
        os.makedirs(_SESSION_DIR, exist_ok=True)

    files = [f for f in os.listdir(_SESSION_DIR) if f.endswith(".json")]
    results = []
    for f in files:
        path = os.path.join(_SESSION_DIR, f)
        mtime = os.path.getmtime(path)
        sid = f.replace(".json", "")
        meta_path = os.path.join(_SESSION_DIR, f"{sid}.meta")
        title = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as mf:
                    meta = json.load(mf)
                    title = meta.get("title")
            except Exception as e:
                logger.warning("list_sessions: corrupt meta for %s: %s", sid, e)

        if not title:
            try:
                with open(path, "r", encoding="utf-8") as sf:
                    data = json.load(sf)
                    if data and len(data) > 0:
                        msg = data[0] if isinstance(data[0], dict) else {}
                        title = str(msg.get("content") or msg.get("text") or "")[:50] or "New Chat"
                    else:
                        title = "New Chat"
            except Exception:
                title = "Untitled Session"

        results.append({"id": sid, "title": title, "updated_at": mtime})

    results.sort(key=lambda x: x["updated_at"], reverse=True)
    return results


@app.post("/api/sessions/new")
def create_session():
    try:
        new_id = f"session_{int(time.time())}"
        loop = get_loop(new_id)
        loop.save_memory()
        set_active_session(new_id, source="cli-api:new")
        return {"id": new_id, "title": "New Chat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")


@app.post("/api/sessions/load")
async def load_session(request: Request):
    try:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        sid = safe_session_id(data.get("id", "default"))
        loop = get_loop(sid)
        apply_runtime_settings(loop)
        set_active_session(sid, source="cli-api:load")
        return {"status": "success", "id": loop.session_id, "history": _sanitize_history_messages(loop.memory, sid)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load session: {str(e)}")


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    sid = safe_session_id(session_id)
    if sid == "default":
        if not _clear_session_files(sid):
            raise HTTPException(status_code=404, detail="Default session not found")
        return {"status": "success", "id": sid, "cleared": True}
    path = session_file_path(sid)
    meta_path = session_file_path(sid, ".meta")
    if not os.path.exists(path) and sid not in _LOOPS:
        return {"status": "error", "id": sid, "deleted": False}
    if os.path.exists(path):
        os.remove(path)
    if os.path.exists(meta_path):
        os.remove(meta_path)
    if sid in _LOOPS:
        del _LOOPS[sid]
    return {"status": "success", "id": sid, "deleted": True}


@app.post("/api/sessions/rename")
async def rename_session(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    new_title = str(data.get("title", "")).strip()[:120]
    path = session_file_path(sid)
    if os.path.exists(path):
        meta_path = session_file_path(sid, ".meta")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"title": new_title}, f)
        return {"status": "success"}
    return {"status": "error"}


_SENTINEL = object()


def _sse_data(value: Any) -> str:
    """Encode every physical line as SSE data so multiline content is preserved."""
    lines = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(f"data: {line}" for line in lines) + "\n\n"

@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        chat_request = build_chat_request(
            data,
            default_source="cli-api:chat",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    prompt = chat_request.prompt
    sid = chat_request.session_id
    provider = chat_request.provider
    model = chat_request.model
    turn_id = chat_request.turn_id
    max_tokens = chat_request.max_tokens
    stream = bool(data.get("stream", False))
    canonical_events = bool(data.get("canonical_events", False))

    try:
        nexus_loop = get_loop(sid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize session: {str(e)}")
    if bool(getattr(nexus_loop, "is_running", False)):
        raise HTTPException(status_code=409, detail="A run is already active for this session")

    # Reset any prior run state before starting a fresh turn (canonical
    # behaviour — the GUI client and tests rely on a clean loop per prompt).
    try:
        nexus_loop.reset()
    except Exception:
        logger.debug("get_loop reset failed for %s", sid, exc_info=True)

    set_active_session(sid, source="cli-api:chat")

    allowed_providers = {
        "openrouter", "qwen", "deepseek", "lm_studio", "anthropic", "openai",
        "gemini", "google_gemini", "groq", "ollama", "llama_cpp", "mistral",
        "cohere", "perplexity", "together", "huggingface", "sambanova",
        "fireworks", "xai", "commandcode", "nvidia"
    }
    safe_provider = provider if provider in allowed_providers else None
    safe_model = model or getattr(nexus_loop, "model", "")

    async def _collect_all(gen):
        parts = []
        try:
            async for chunk in gen:
                if chunk.get("type") == "content":
                    parts.append(chunk["data"])
        except Exception as e:
            safe_err = str(e).replace('\n', ' ').replace('\r', '')
            parts.append(f"[NEXUS_SYSTEM_ERROR]: {safe_err}")
        finally:
            if hasattr(gen, "aclose"):
                await gen.aclose()
        return "".join(parts)

    async def async_generator():
        event_sequence = 0
        previous_sink = nexus_loop.work_event_sink
        event_queue: asyncio.Queue = asyncio.Queue()
        chunk_queue: asyncio.Queue = asyncio.Queue()
        owner_loop = asyncio.get_running_loop()

        def stream_event_sink(payload):
            nonlocal event_sequence
            event_sequence += 1
            event = CanonicalEvent.from_work_event(dict(payload), sid, event_sequence).to_dict()
            _append_work_event(sid, event)
            owner_loop.call_soon_threadsafe(event_queue.put_nowait, event)
            return event

        async def pump_run():
            try:
                async for chunk in nexus_loop.stream_run(
                    prompt,
                    provider=safe_provider,
                    model=safe_model,
                    max_tokens=max_tokens,
                    turn_id=turn_id,
                ):
                    await chunk_queue.put(("chunk", chunk))
            except asyncio.TimeoutError:
                await chunk_queue.put(("error", "Response timed out after 30 seconds"))
            except Exception as exc:
                await chunk_queue.put(("error", str(exc)))
            finally:
                await chunk_queue.put(("done", None))

        if canonical_events:
            nexus_loop.work_event_sink = stream_event_sink
        producer = asyncio.create_task(pump_run())
        try:
            finished = False
            while not finished or not event_queue.empty():
                if not event_queue.empty():
                    event = event_queue.get_nowait()
                    yield f"event: nexus.event\nid: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    continue

                event_wait = asyncio.create_task(event_queue.get()) if canonical_events else None
                chunk_wait = asyncio.create_task(chunk_queue.get())
                waits = {chunk_wait}
                if event_wait is not None:
                    waits.add(event_wait)
                completed, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

                if event_wait is not None and event_wait in completed:
                    event = event_wait.result()
                    yield f"event: nexus.event\nid: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if chunk_wait in completed:
                    kind, value = chunk_wait.result()
                    if kind == "done":
                        finished = True
                    elif kind == "error":
                        safe_err = str(value).replace('\n', ' ').replace('\r', '')
                        yield "event: error\n" + _sse_data(f"[NEXUS_SYSTEM_ERROR]: {safe_err}")
                    elif value.get("type") == "content":
                        yield _sse_data(value['data'])
        except GeneratorExit:
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            safe_err = str(e).replace('\n', ' ').replace('\r', '')
            yield "event: error\n" + _sse_data(f"[NEXUS_SYSTEM_ERROR]: {safe_err}")
        finally:
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            if canonical_events and nexus_loop.work_event_sink is stream_event_sink:
                nexus_loop.work_event_sink = previous_sink

    if stream:
        return StreamingResponse(async_generator(), media_type="text/event-stream")
    else:
        gen = nexus_loop.stream_run(
            prompt,
            provider=safe_provider,
            model=safe_model,
            max_tokens=max_tokens,
            turn_id=turn_id,
        )
        text = await _collect_all(gen)
        return {"response": text}


@app.post("/api/chat/{session_id}/cancel")
def cancel_chat(session_id: str, turn_id: str = ""):
    """Cancel the active run for a server-owned session."""
    sid = safe_session_id(session_id)
    nexus_loop = _LOOPS.get(sid)
    if nexus_loop is None:
        raise HTTPException(status_code=404, detail="Active session not found")
    nexus_loop.abort()
    run_id = str(turn_id or getattr(nexus_loop, "_current_turn_id", "") or sid)
    return {
        "status": "cancelled",
        "run_id": run_id,
        "event": {
            "id": f"run_{run_id}",
            "type": "run.cancelled",
            "event_type": "run.cancelled",
            "run_id": run_id,
            "turn_id": run_id,
            "kind": "run",
            "title": "Run cancelled",
            "status": "cancelled",
            "visibility": "public",
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# OPENAI-COMPATIBLE ENDPOINTS (OpenClaw-inspired)
# ═════════════════════════════════════════════════════════════════════════════

def _get_available_models() -> list:
    """Return list of known models from provider config."""
    models = []
    try:
        prov_path = os.path.join(_PROJECT_ROOT, "config", "provider.yml")
        if os.path.isfile(prov_path) and yaml:
            with open(prov_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for name, cfg in data.items():
                if isinstance(cfg, dict) and cfg.get("model"):
                    models.append({
                        "id": cfg["model"],
                        "object": "model",
                        "created": int(os.path.getmtime(prov_path)),
                        "owned_by": name,
                    })
    except Exception:
        logger.warning("server:816 _get_available_models: suppressed error", exc_info=True)
        pass
    if not models:
        models.append({
            "id": "deepseek-chat",
            "object": "model",
            "created": 0,
            "owned_by": "nexus",
        })
    return models


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing."""
    return {"object": "list", "data": _get_available_models()}


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    """OpenAI-compatible chat completions endpoint.

    Accepts standard OpenAI request body, streams or returns
    OpenAI-formatted response. Any OpenAI-compatible client can use this.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages: list = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    model: str = str(body.get("model", "deepseek-chat"))
    stream: bool = bool(body.get("stream", False))
    try:
        max_tokens = int(body.get("max_tokens", body.get("max_completion_tokens", 4096)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="max_tokens must be an integer")
    if not 1 <= max_tokens <= 1_000_000:
        raise HTTPException(status_code=400, detail="max_tokens must be between 1 and 1000000")

    # Extract user prompt from messages
    prompt_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            prompt_parts.append(f"[System]: {content}")
        elif role == "user":
            prompt_parts.append(f"{content}")
        elif role == "assistant":
            prompt_parts.append(f"[Assistant]: {content}")
    prompt = "\n".join(prompt_parts).strip()[:50000]

    if not prompt:
        raise HTTPException(status_code=400, detail="No user message found")

    # Map model name to provider
    provider_map = {
        "deepseek": ("deepseek", model),
        "gpt": ("openai", model),
        "claude": ("anthropic", model),
        "gemini": ("gemini", model),
    }
    provider_name = "deepseek"
    resolved_model = model
    for key, (prov, _) in provider_map.items():
        if model.lower().startswith(key):
            provider_name = prov
            break

    sid = f"openai_{uuid.uuid4().hex}"
    try:
        nexus_loop = get_loop(sid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session init failed: {e}")

    request_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    async def _stream_openai():
        try:
            async for chunk in nexus_loop.stream_run(
                prompt,
                provider=provider_name,
                model=resolved_model,
                max_tokens=max_tokens,
            ):
                if chunk.get("type") == "content":
                    data = chunk["data"]
                    sse = {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": data}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(sse)}\n\n"
            # Final [DONE] chunk
            done = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    if stream:
        return StreamingResponse(_stream_openai(), media_type="text/event-stream")

    # Non-streaming: collect all content
    full_text = ""
    async for chunk in nexus_loop.stream_run(
        prompt,
        provider=provider_name,
        model=resolved_model,
        max_tokens=max_tokens,
    ):
        if chunk.get("type") == "content":
            full_text += chunk["data"]

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": full_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(full_text), "total_tokens": len(prompt) + len(full_text)},
    }


@app.get("/api/history")
def get_history(session_id: str = "default"):
    try:
        loop = get_loop(session_id)
        loop.sync_memory()
        return _sanitize_history_messages(loop.memory, safe_session_id(session_id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get history: {str(e)}")


@app.get("/api/runs")
def list_runs(session_id: str = "", limit: int = 100):
    """List recent durable run contexts for inspector and replay surfaces."""
    runs = []
    for item in list_run_contexts(_RUN_ROOT, session_id=session_id, limit=limit):
        public_item = dict(item)
        public_item.pop("_path", None)
        public_item["work_events"] = work_event_run_summary(
            str(public_item.get("session_id") or session_id or "default"),
            str(public_item.get("run_id") or ""),
        )
        runs.append(public_item)
    return {"status": "success", "runs": runs}


@app.get("/api/runs/{session_id}/{run_id}")
def get_run_context(session_id: str, run_id: str, include_events: bool = True, limit: int = 1000):
    """Return one durable run context plus public work-event replay."""
    sid = safe_session_id(session_id)
    context = load_run_context(_RUN_ROOT, sid, run_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Run context not found")
    resolved_run_id = str(context.get("run_id") or run_id)
    response: Dict[str, Any] = {
        "status": "success",
        "run": context,
        "work_events": work_event_run_summary(sid, resolved_run_id),
    }
    if include_events:
        events = list_work_events(sid, limit=limit, turn_id=resolved_run_id)
        response["events"] = events
        response["next_sequence"] = max((int(event.get("sequence") or 0) for event in events), default=0)
    return response


@app.get("/api/work-events")
def get_work_events(request: Request, session_id: str = "default", limit: int = 200, turn_id: str = "", after_sequence: int = 0):
    header_cursor = request.headers.get("Last-Event-ID", "").strip()
    if header_cursor:
        try:
            after_sequence = max(after_sequence, int(header_cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer sequence")
    events = list_work_events(session_id, limit=limit, turn_id=turn_id, after_sequence=after_sequence)
    next_sequence = max((int(event.get("sequence") or 0) for event in events), default=after_sequence)
    return {"events": events, "after_sequence": after_sequence, "next_sequence": next_sequence}


@app.post("/api/work-events/run-command-stream")
async def run_work_command_stream(request: Request):
    """Run a workspace command and stream its real output to the GUI."""
    data = await request.json()
    sid = safe_session_id(str(data.get("session_id") or "terminal"))
    command = str(data.get("command") or data.get("target") or "").strip()
    profile = str(data.get("profile") or "pwsh").strip().lower()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")
    if len(command) > 4000:
        raise HTTPException(status_code=413, detail="Command is too large")
    if profile not in {"pwsh", "cmd", "bash", "wsl"}:
        raise HTTPException(status_code=400, detail="Unsupported terminal profile")

    # Enforce the session's terminal permission policy before touching the
    # sandbox. A restrictive mode (ask/default/allowlist) must block the
    # command here rather than executing it — the GUI surface is non-interactive
    # and cannot perform a live approval handshake for a streaming command.
    decision = _check_gui_terminal_permission(sid, str(data.get("turn_id", "")), command)
    if not getattr(decision, "granted", True):
        blocked = _append_work_event(sid, {
            "kind": "command", "type": "command", "action": "Run command",
            "title": "Run command", "target": command, "command": command,
            "profile": profile, "status": "blocked",
            "reason": "Command blocked by permission policy",
        })
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'blocked', 'event': blocked, 'command': command, 'message': 'Command blocked by permission policy'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    started = _append_work_event(sid, {
        "kind": "command", "type": "command", "action": "Run command",
        "title": "Run command", "target": command, "command": command,
        "profile": profile, "status": "running",
    })

    async def event_stream():
        output_parts: list[str] = []

        def sse(payload: Dict[str, Any]) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield sse({"type": "start", "event": started, "command": command, "profile": profile})
        try:
            from sandbox.sandbox_manager import SovereignSandbox
            sandbox = SovereignSandbox(_PROJECT_ROOT)
            async for text in sandbox.stream_execute(command, _PROJECT_ROOT):
                output_parts.append(text)
                yield sse({"type": "chunk", "stream": "stderr" if text.startswith("[SANDBOX_") else "stdout", "text": text})
            output = "".join(output_parts)
            exit_code = sandbox.last_exit_code if sandbox.last_exit_code is not None else 0
            status = "done" if exit_code == 0 else "error"
            completed = _append_work_event(sid, {
                **started, "id": f"{started.get('id')}_result", "status": status,
                "stdout": output, "stderr": "", "output": output,
                "exit_code": exit_code, "completed_at": time.time(),
            })
            yield sse({"type": "done", "status": status, "event": completed, "output": output, "exit_code": exit_code})
        except Exception as exc:
            message = str(exc)
            completed = _append_work_event(sid, {
                **started, "id": f"{started.get('id')}_result", "status": "error",
                "stdout": "", "stderr": message, "output": message,
                "completed_at": time.time(),
            })
            yield sse({"type": "chunk", "stream": "stderr", "text": message})
            yield sse({"type": "done", "status": "error", "event": completed, "output": message})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── New CLI Backend Endpoints ────────────────────────────────────────────────

_TASKS: Dict[str, dict] = _load_tasks()
_TASK_COUNTER = max([int(k.split("_")[1]) for k in _TASKS if "_" in k] or [0])


@app.get("/api/skills")
def list_skills():
    """List available skills from project config and .opencode/skills."""
    summary = _config_summary()
    by_name = {skill["name"]: skill for skill in summary["skills"]}
    skills_dir = os.path.join(_PROJECT_ROOT, ".opencode", "skills")
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, name, "SKILL.md")
            desc = ""
            if os.path.exists(skill_path):
                try:
                    with open(skill_path, "r", encoding="utf-8") as f:
                        desc = f.readline().strip().lstrip("# ")[:80]
                except Exception:
                    logger.warning("server:974 list_skills: suppressed error", exc_info=True)
                    pass
            by_name.setdefault(name, {"name": name, "description": desc or "NEXUS skill", "enabled": True})
    return {"skills": sorted(by_name.values(), key=lambda item: item["name"])}


@app.get("/api/tools")
def list_tools():
    """List registered tools from ToolRegistry."""
    summary = _config_summary()
    config_tools = {tool["name"]: tool for tool in summary["tools"]}
    try:
        from tools.nexus_tools.registry import ToolRegistry
        registry = ToolRegistry(_PROJECT_ROOT)
        tools = []
        registry_summary = registry.list_tools(include_unavailable=True)
        for name in sorted(registry_summary):
            tool = registry.get(name)
            if tool:
                cfg = config_tools.get(name, {})
                active = bool(cfg.get("enabled", True))
                status = tool.availability()
                tools.append({
                    "name": name,
                    "description": cfg.get("description") or str(tool.schema.get("description", ""))[:120],
                    "read_only": getattr(tool, "is_read_only", lambda: False)(),
                    "safe": getattr(tool, "is_concurrency_safe", lambda: False)(),
                    "enabled": active,
                    "available": bool(status.get("available")) and active,
                    "availability_reason": "disabled_by_config" if not active else status.get("reason", "unknown"),
                    "missing_env": status.get("missing_env", []),
                    "has_handler": tool.instance is not None,
                })
        seen = {tool["name"] for tool in tools}
        for name, cfg in config_tools.items():
            if name not in seen:
                tools.append({
                    "name": name,
                    "description": cfg.get("description", ""),
                    "read_only": False,
                    "safe": False,
                    "enabled": bool(cfg.get("enabled", True)),
                    "available": False,
                    "availability_reason": "custom_config_only",
                    "missing_env": [],
                    "has_handler": False,
                })
        return {"tools": tools}
    except Exception as e:
        return {"tools": list(config_tools.values()), "error": str(e)}


@app.get("/api/agents")
def list_agents():
    """List available agents from .opencode/agents and hive personas."""
    agents = []
    seen = set()

    agents_dir = os.path.join(_PROJECT_ROOT, ".opencode", "agents")
    if os.path.isdir(agents_dir):
        for fname in sorted(os.listdir(agents_dir)):
            if fname.endswith((".yaml", ".yml")):
                name = fname.rsplit(".", 1)[0]
                path = os.path.join(agents_dir, fname)
                desc = ""
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.lower().startswith("description:"):
                                desc = line.split(":", 1)[1].strip()[:80]
                                break
                except Exception:
                    logger.warning("server:1034 list_agents: suppressed error", exc_info=True)
                    pass
                agents.append({
                    "id": name,
                    "name": name.replace("-", " ").title(),
                    "status": "idle",
                    "description": desc or "NEXUS agent"
                })
                seen.add(name.lower())

    try:
        from hive.engine import NexusHiveEngine
        hive = NexusHiveEngine(_PROJECT_ROOT)
        personas = hive.list_personas()
        for role, desc in personas.items():
            key = role.lower()
            if key not in seen:
                agents.append({
                    "id": role,
                    "name": role.replace("_", " ").title(),
                    "status": "idle",
                    "description": str(desc)[:120] or "Hive worker agent"
                })
                seen.add(key)
    except Exception:
        logger.warning("server:1058 : suppressed error", exc_info=True)
        pass

    try:
        from providers.profiles import load_profile_store
        store = load_profile_store()
        for profile in store.list_profiles():
            key = profile.name.lower()
            if key not in seen:
                agents.append({
                    "id": profile.name,
                    "name": profile.name.replace("-", " ").title(),
                    "status": "idle",
                    "description": f"NEXUS profile: {profile.name}"
                })
                seen.add(key)
    except Exception:
        logger.warning("server:1074 : suppressed error", exc_info=True)
        pass

    return {"agents": agents}


@app.get("/api/plugins")
def list_plugins():
    """List enabled plugins from project settings."""
    return {"plugins": _config_summary()["plugins"]}


@app.get("/api/mcp")
def list_mcp():
    """List MCP servers from nexus_config.yaml."""
    return {"mcp": _config_summary()["mcp"]}


@app.get("/api/providers")
def list_provider_config():
    """List configured providers from nexus config and kernel factory."""
    providers = _config_summary()["providers"]

    try:
        from providers.factory import NexusProviderFactory
        factory = NexusProviderFactory()
    except Exception:
        factory = None

    active_providers_from_kernel = set()
    if factory:
        try:
            from providers.profiles import load_profile_store
            store = load_profile_store()
            for prov in store.providers():
                active_providers_from_kernel.add(prov.lower())
        except Exception:
            logger.warning("server:1110 list_provider_config: suppressed error", exc_info=True)
            pass

    for p in providers:
        if p["id"].lower() in active_providers_from_kernel:
            p["active"] = True

    return {
        "providers": providers,
        "runtime": {
            "provider": _RUNTIME_SETTINGS.get("provider") or "",
            "model": _RUNTIME_SETTINGS.get("model") or "",
        }
    }


@app.get("/api/features")
def list_features():
    """List runtime feature flags from nexus_config.yaml."""
    return {"features": _config_summary()["features"]}


@app.post("/api/approve")
async def approve_tool_request(request: Request):
    """Resolve a pending Co-Pilot (ask-mode) tool approval.

    The GUI has always POSTed here from useStreamChat.respondApproval(), but
    no backend route existed, so ask-mode approvals went nowhere and the run
    stalled until it timed out. Decisions are brokered by
    permissions.approval_broker so any surface can answer.
    """
    from permissions.approval_broker import get_approval_broker, normalize_decision

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    request_id = str(data.get("request_id") or "").strip()
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id is required")

    decision = normalize_decision(data.get("decision"))
    matched = get_approval_broker().resolve(request_id, decision)
    return {"ok": True, "request_id": request_id, "decision": decision, "matched": matched}


@app.get("/api/approve/pending")
def list_pending_approvals(session_id: str = ""):
    """Outstanding approvals, so a reconnecting client can re-render them."""
    from permissions.approval_broker import get_approval_broker

    return {"pending": get_approval_broker().pending(safe_session_id(session_id) if session_id else "")}


@app.get("/api/files/read")
def read_workspace_file(path: str = ""):
    """Stream a single workspace file for the GUI file explorer / download.

    The frontend (FileExplorer.tsx, lib/api.ts) has always linked to this
    route, but no backend implemented it, so every preview/download 404'd.
    Path containment is enforced by safe_workspace_read_path().
    """
    resolved = safe_workspace_read_path(path)
    from fastapi.responses import FileResponse
    return FileResponse(
        resolved,
        filename=os.path.basename(resolved),
        media_type="application/octet-stream",
    )


@app.post("/api/files/list")
async def list_files(request: Request):
    """List directory contents relative to project root."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    relative_path = str(data.get("path", ".")).strip()

    target = os.path.abspath(os.path.join(_PROJECT_ROOT, relative_path))
    if os.path.commonpath([_PROJECT_ROOT, target]) != _PROJECT_ROOT:
        raise HTTPException(status_code=403, detail="Path is outside project root")

    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail=f"Path not found: {relative_path}")

    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {relative_path}")

    try:
        entries = sorted(os.listdir(target))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {relative_path}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read directory: {str(e)}")

    files = []
    for name in entries:
        if name.lower() in _WINDOWS_RESERVED or name.endswith("."):
            continue
        full_path = os.path.join(target, name)
        try:
            rel_path = os.path.relpath(full_path, _PROJECT_ROOT).replace("\\", "/")
        except ValueError:
            rel_path = name
        files.append({
            "name": name,
            "path": rel_path,
            "isDirectory": os.path.isdir(full_path),
            "children": [],
        })

    return {"files": files}


@app.post("/api/manage")
async def manage_runtime(request: Request):
    """Real config-backed management for tools, skills, MCP, plugins, providers, and runtime features."""
    data = await request.json()
    action = str(data.get("action", "")).strip().lower()
    target_type = str(data.get("type", "")).strip().lower()
    name = str(data.get("name", "")).strip()
    value = data.get("value")

    if action in {"on", "true", "start"}:
        action = "enable"
    if action in {"off", "false", "stop"}:
        action = "disable"

    config_actions = {"enable", "disable", "reload", "reset", "status", "set", "add", "remove", "model"}
    if action not in config_actions:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

    if action == "status":
        return {"status": "success", "summary": _config_summary()}

    if action == "reload":
        if target_type in {"nexus", "runtime", "loops", "all", ""}:
            reset = _clear_runtime("reload requested")
            return {"status": "success", "target": target_type or "runtime", **reset}

        if target_type in {"tool", "tools"}:
            try:
                from tools.nexus_tools.registry import ToolRegistry
                ToolRegistry._reset_instance()
            except Exception:
                logger.warning("server:1208 : suppressed error", exc_info=True)
                pass
            _clear_runtime("tools reloaded")

        elif target_type in {"skill", "skills"}:
            try:
                from skills import NexusSkillMaster
                NexusSkillMaster._reset_instance()
            except Exception:
                logger.warning("server:1216 : suppressed error", exc_info=True)
                pass
            _clear_runtime("skills reloaded")

        elif target_type in {"mcp", "mcps", "mcp_server"}:
            _clear_runtime("mcp config reloaded")

        elif target_type in {"provider", "providers"}:
            try:
                from providers.factory import NexusProviderFactory
                NexusProviderFactory._reset_instance()
            except Exception:
                logger.warning("server:1227 : suppressed error", exc_info=True)
                pass
            _clear_runtime("providers reloaded")

        elif target_type == "config":
            try:
                from config.config_loader import NexusConfigLoader
                NexusConfigLoader().reload()
            except Exception:
                logger.warning("server:1235 : suppressed error", exc_info=True)
                pass

        return {"status": "success", "target": target_type, "summary": _config_summary()}

    if action == "reset":
        if target_type in {"nexus", "runtime", "loops", "all", ""}:
            _RUNTIME_SETTINGS.update({
                "model": "",
                "provider": "",
                "mode": "auto",
                "sandbox_tier": "normal",
                "permission_allowlist": [],
                "agent": "",
                "goal": "",
                "additional_dirs": [],
            })
            _save_runtime_preferences()
            reset = _clear_runtime("reset requested")
            return {"status": "success", "target": target_type or "runtime", **reset}
        if target_type == "tasks":
            _TASKS.clear()
            _save_tasks(_TASKS)
            return {"status": "success", "target": "tasks", "cleared": True}
        raise HTTPException(status_code=400, detail=f"Reset not supported for {target_type}")

    if target_type in {"hive", "evolution", "scheduler", "reminders", "health"} and not name:
        name = target_type

    if not target_type or not name:
        raise HTTPException(status_code=400, detail="type and name are required")

    config = _load_nexus_config()

    if target_type in {"tool", "tools"}:
        configs = config.setdefault("custom_tool_configs", {})
        entry = configs.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            configs[name] = entry
        if action == "enable":
            entry["active"] = True
            _set_disabled(config, "disabled_tools", name, False)
        elif action == "disable":
            entry["active"] = False
            _set_disabled(config, "disabled_tools", name, True)
        elif action == "set":
            if isinstance(value, dict):
                entry.update(value)
            else:
                raise HTTPException(status_code=400, detail="tool set requires object value")
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for tools")
        _save_nexus_config(config)
        _clear_runtime("tool config changed")
        return {"status": "success", "type": "tool", "name": name, "enabled": name not in config.get("disabled_tools", []) and bool(entry.get("active", True))}

    if target_type in {"skill", "skills"}:
        configs = config.setdefault("custom_skill_configs", {})
        entry = configs.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            configs[name] = entry
        if action == "enable":
            entry["active"] = True
            _set_disabled(config, "disabled_skills", name, False)
        elif action == "disable":
            entry["active"] = False
            _set_disabled(config, "disabled_skills", name, True)
        elif action == "set":
            if isinstance(value, dict):
                entry.update(value)
            else:
                raise HTTPException(status_code=400, detail="skill set requires object value")
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for skills")
        _save_nexus_config(config)
        _clear_runtime("skill config changed")
        return {"status": "success", "type": "skill", "name": name, "enabled": name not in config.get("disabled_skills", []) and bool(entry.get("active", True))}

    if target_type in {"mcp", "mcps", "mcp_server"}:
        servers = config.setdefault("mcp_servers", {})
        entry = servers.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            servers[name] = entry
        if action == "enable":
            entry["active"] = True
        elif action == "disable":
            entry["active"] = False
        elif action in {"add", "set"}:
            if isinstance(value, dict):
                entry.update(value)
            else:
                raise HTTPException(status_code=400, detail="mcp add/set requires object value")
        elif action == "remove":
            servers.pop(name, None)
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for MCP")
        _save_nexus_config(config)
        _clear_runtime("mcp config changed")
        return {"status": "success", "type": "mcp", "name": name, "active": bool(entry.get("active", False)) if action != "remove" else False}

    if target_type in {"plugin", "plugins"}:
        settings = _load_claude_settings(strict=True)
        enabled = settings.setdefault("enabledPlugins", {})
        if not isinstance(enabled, dict):
            enabled = {}
            settings["enabledPlugins"] = enabled
        if action == "enable":
            enabled[name] = True
        elif action == "disable":
            enabled[name] = False
        elif action == "remove":
            enabled.pop(name, None)
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for plugins")
        _save_claude_settings(settings)
        return {"status": "success", "type": "plugin", "name": name, "enabled": bool(enabled.get(name, False))}

    if target_type in {"provider", "providers"}:
        entry = _provider_entry(config, name)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Provider not found: {name}")
        if action == "enable":
            entry["active"] = True
            _RUNTIME_SETTINGS["provider"] = name
        elif action == "disable":
            entry["active"] = False
            if _RUNTIME_SETTINGS.get("provider") == name:
                _RUNTIME_SETTINGS["provider"] = ""
        elif action == "model":
            model = str(value or "").strip()
            if not model:
                raise HTTPException(status_code=400, detail="model value is required")
            entry["model"] = model
            if _RUNTIME_SETTINGS.get("provider") == name:
                _RUNTIME_SETTINGS["model"] = model
        elif action in {"set", "add"}:
            if isinstance(value, dict):
                entry.update(value)
            else:
                raise HTTPException(status_code=400, detail="provider set/add requires object value")
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for providers")
        _save_nexus_config(config)
        apply_runtime_to_all_loops()
        return {"status": "success", "type": "provider", "name": name, "active": bool(entry.get("active", False)), "model": entry.get("model", "")}

    if target_type in {"feature", "features", "hive", "evolution", "scheduler", "reminders", "health"}:
        feature_name = name if target_type in {"feature", "features"} else target_type
        features = _runtime_features(config)
        if action == "enable":
            features[feature_name] = True
        elif action == "disable":
            features[feature_name] = False
        else:
            raise HTTPException(status_code=400, detail=f"{action} not supported for features")
        _save_nexus_config(config)
        _clear_runtime("feature config changed")
        return {"status": "success", "type": "feature", "name": feature_name, "enabled": bool(features[feature_name])}

    if target_type == "config":
        if action != "set":
            raise HTTPException(status_code=400, detail="config supports only set")
        _set_dotted(config, name, value)
        _save_nexus_config(config)
        _clear_runtime("config changed")
        return {"status": "success", "type": "config", "path": name, "value": _parse_config_value(value)}

    raise HTTPException(status_code=400, detail=f"Unsupported target type: {target_type}")


@app.get("/api/tasks")
def list_tasks():
    """List current tasks."""
    tasks = []
    for task in _TASKS.values():
        subject = str(task.get("subject", "")).strip().lower()
        agent = str(task.get("agent", "") or "").strip().lower()
        if agent == "test":
            continue
        if subject in {"e2e task", "test task"}:
            continue
        tasks.append(task)
    return {"tasks": tasks}


@app.post("/api/tasks")
async def create_task(request: Request):
    """Create a new task (persisted to disk)."""
    global _TASK_COUNTER
    data = await request.json()
    _TASK_COUNTER += 1
    tid = f"task_{_TASK_COUNTER}"
    task = {
        "id": tid,
        "subject": str(data.get("subject", "New Task"))[:120],
        "status": "pending",
        "agent": data.get("agent"),
        "created_at": time.time(),
    }
    _TASKS[tid] = task
    _save_tasks(_TASKS)
    return {"status": "created", "task": task}


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    """Update task status (persisted to disk)."""
    if task_id not in _TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    data = await request.json()
    if "status" in data:
        _TASKS[task_id]["status"] = data["status"]
    if "subject" in data:
        _TASKS[task_id]["subject"] = str(data["subject"])[:120]
    _save_tasks(_TASKS)
    return {"status": "updated", "task": _TASKS[task_id]}


@app.get("/api/status")
def get_status():
    """Full system status."""
    latest = list(_LOOPS.values())[-1] if _LOOPS else None
    active_provider = None
    if latest:
        try:
            active_provider = getattr(latest.brain.base_router, "provider", None)
        except Exception:
            active_provider = None
    try:
        agent_data = list_agents()
        real_agent_count = len(agent_data.get("agents", []))
    except Exception:
        real_agent_count = 0

    status = {
        "model": _RUNTIME_SETTINGS.get("model") or getattr(active_provider, "model", "") or "auto",
        "mode": _normalize_permission_mode(_RUNTIME_SETTINGS.get("mode") or "auto"),
        "provider": _RUNTIME_SETTINGS.get("provider") or getattr(active_provider, "provider_name", "") or "auto",
        "agent": _RUNTIME_SETTINGS.get("agent") or "",
        "goal": _RUNTIME_SETTINGS.get("goal") or "",
        "sandbox_tier": _normalize_sandbox_tier(_RUNTIME_SETTINGS.get("sandbox_tier", "normal")),
        "permission_modes": ["auto", "all", "allowlist", "ask"],
        "permission_allowlist": _RUNTIME_SETTINGS.get("permission_allowlist") or [],
        "additional_dirs": _RUNTIME_SETTINGS.get("additional_dirs") or [],
        "health": "ok",
        "uptime": 0,
        "session_count": len(_LOOPS),
        "agent_count": real_agent_count,
        "task_count": len(_TASKS),
        "version": "2.1.0"
    }
    return status


@app.post("/api/mode")
async def set_mode(request: Request):
    """Switch permission mode."""
    data = await request.json()
    mode = _normalize_permission_mode(str(data.get("mode", "auto")))
    allowed = {"auto", "all", "allowlist", "ask", "plan", "acceptedits", "accept", "dontask", "bypass", "approve", "default", "pre_authorized", "checklist"}
    if mode not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Choose from: {', '.join(allowed)}")
    _RUNTIME_SETTINGS["mode"] = mode
    apply_runtime_to_all_loops()
    _save_runtime_preferences()
    return {"status": "success", "mode": mode}


@app.get("/api/permissions")
def get_permissions():
    """Return permission mode and saved allow-list."""
    from permissions import PermissionSystem

    return {
        "status": "success",
        "mode": _normalize_permission_mode(_RUNTIME_SETTINGS.get("mode") or "auto"),
        "available": ["auto", "all", "allowlist", "ask"],
        "allowlist": _RUNTIME_SETTINGS.get("permission_allowlist") or [],
        "recent_decisions": PermissionSystem().get_decision_log(limit=20),
    }


@app.get("/api/permissions/decisions")
def get_permission_decisions(limit: int = 50):
    """Return recent permission decisions with scrubbed action previews."""
    from permissions import PermissionSystem

    return {
        "status": "success",
        "decisions": PermissionSystem().get_decision_log(limit=limit),
    }


@app.post("/api/permissions")
async def set_permissions(request: Request):
    """Set permission mode and optionally update saved allow-list entries."""
    data = await request.json()
    mode = _normalize_permission_mode(str(data.get("mode", _RUNTIME_SETTINGS.get("mode") or "auto")))
    if mode not in {"auto", "all", "allowlist", "ask"}:
        raise HTTPException(status_code=400, detail="Invalid permission mode. Choose from: auto, all, allowlist, ask")
    _RUNTIME_SETTINGS["mode"] = mode

    add = str(data.get("add") or "").strip()
    remove = str(data.get("remove") or "").strip()
    allowlist = [str(item).strip() for item in (_RUNTIME_SETTINGS.get("permission_allowlist") or []) if str(item).strip()]
    if add and add not in allowlist:
        allowlist.append(add)
    if remove:
        allowlist = [item for item in allowlist if item != remove]
    if isinstance(data.get("allowlist"), list):
        allowlist = [str(item).strip() for item in data["allowlist"] if str(item).strip()]
    _RUNTIME_SETTINGS["permission_allowlist"] = allowlist

    apply_runtime_to_all_loops()
    _save_runtime_preferences()
    return {"status": "success", "mode": mode, "allowlist": allowlist}


@app.get("/api/model")
def get_model():
    """Return the currently active model."""
    return {
        "status": "success",
        "model": _RUNTIME_SETTINGS.get("model") or "",
        "provider": _RUNTIME_SETTINGS.get("provider") or "",
    }


@app.post("/api/model")
async def set_model(request: Request):
    """Switch model."""
    data = await request.json()
    model = str(data.get("model", "")).strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    _RUNTIME_SETTINGS["model"] = model
    apply_runtime_to_all_loops()
    return {"status": "success", "model": model}


@app.post("/api/provider")
async def set_provider(request: Request):
    """Switch provider override."""
    data = await request.json()
    provider = str(data.get("provider", "")).strip().lower().replace(" ", "_")
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    _RUNTIME_SETTINGS["provider"] = provider
    apply_runtime_to_all_loops()
    return {"status": "success", "provider": provider}


@app.post("/api/agent")
async def set_agent(request: Request):
    """Switch agent."""
    data = await request.json()
    agent = str(data.get("agent", "")).strip()
    _RUNTIME_SETTINGS["agent"] = agent
    apply_runtime_to_all_loops()
    return {"status": "success", "agent": agent}


@app.post("/api/command")
async def run_command(request: Request):
    """Execute a slash command — shared across TUI, GUI, and gateways.

    Request body:
        {"command": "/status", "args": ["/status"]}

    Returns CommandResult with formatted output for Rich rendering.
    """
    from nexus.commands import get_registry, CommandContext

    data = await request.json()
    raw = str(data.get("command", "")).strip()
    args_raw = data.get("args", raw)

    registry = get_registry()
    cmd = registry.get(raw)
    if not cmd:
        raise HTTPException(status_code=404, detail=f"Unknown command: {raw}")

    ctx = CommandContext(
        session_id=_RUNTIME_SETTINGS.get("session_id", "default"),
        mode=_RUNTIME_SETTINGS.get("mode", "auto"),
        provider=_RUNTIME_SETTINGS.get("provider", ""),
        model=_RUNTIME_SETTINGS.get("model", ""),
        thinking=_RUNTIME_SETTINGS.get("thinking", True),
        extra={"args": args_raw},
    )
    result = await cmd.execute(ctx)
    return {
        "status": "success" if result.success else "error",
        "output": result.output,
        "formatted": result.formatted,
        "content_type": result.content_type,
        "data": result.data,
        "error": result.error if not result.success else "",
    }


@app.get("/api/goal")
def get_goal_state():
    """Return the active Nexus goal."""
    goal = str(_RUNTIME_SETTINGS.get("goal") or "")
    return {"status": "success", "goal": goal, "active": bool(goal)}


@app.post("/api/goal")
async def set_goal_state(request: Request):
    """Set or clear the active Nexus goal used by the agent loop."""
    data = await request.json()
    raw_goal = str(data.get("goal", "")).strip()
    normalized = raw_goal.lower()
    if normalized in {"", "clear", "stop", "off", "reset", "none", "cancel"}:
        _RUNTIME_SETTINGS["goal"] = ""
        apply_runtime_to_all_loops()
        return {"status": "success", "goal": "", "active": False}

    _RUNTIME_SETTINGS["goal"] = raw_goal[:1000]
    apply_runtime_to_all_loops()
    return {"status": "success", "goal": _RUNTIME_SETTINGS["goal"], "active": True}


@app.get("/api/sandbox")
def get_sandbox():
    """Return the current sandbox tier."""
    return {
        "status": "success",
        "tier": _normalize_sandbox_tier(_RUNTIME_SETTINGS.get("sandbox_tier", "normal")),
        "available": ["no_sandbox", "normal", "docker"],
        "labels": {"no_sandbox": "none", "normal": "simple", "docker": "docker"},
    }


@app.post("/api/sandbox")
async def set_sandbox(request: Request):
    """Set the sandbox tier: no_sandbox, normal, or docker."""
    data = await request.json()
    tier = _normalize_sandbox_tier(str(data.get("tier", "")))
    valid = {"no_sandbox", "normal", "docker"}
    if tier not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid sandbox tier. Choose from: {', '.join(sorted(valid))}")
    _RUNTIME_SETTINGS["sandbox_tier"] = tier
    os.environ["NEXUS_SANDBOX_TIER"] = tier
    apply_runtime_to_all_loops()
    _save_runtime_preferences()
    return {"status": "success", "tier": tier}


@app.post("/api/add-dir")
async def add_working_dir(request: Request):
    """Add an extra local directory to the active runtime context."""
    data = await request.json()
    raw_path = str(data.get("path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="path is required")
    target = os.path.abspath(os.path.join(_PROJECT_ROOT, raw_path)) if not os.path.isabs(raw_path) else os.path.abspath(raw_path)
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail=f"Directory not found: {target}")
    dirs = _RUNTIME_SETTINGS.setdefault("additional_dirs", [])
    if target not in dirs:
        dirs.append(target)
    apply_runtime_to_all_loops()
    return {"status": "success", "path": target, "additional_dirs": dirs}


@app.post("/api/run")
async def execute_bash_command(request: Request):
    """Run a bash command (read-only or safe only)."""
    data = await request.json()
    command = str(data.get("command", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="No command provided")

    # Reject dangerous commands (uses word-boundary checks)
    lowered = command.lower()
    if re.search(r'\bsudo\b', lowered) or (re.search(r'\brm\b', lowered) and '-rf' in lowered):
        raise HTTPException(status_code=403, detail="Dangerous command blocked")
    for d in ("mkfs", "dd if=", "> /dev", ":(){"):
        if d in lowered:
            raise HTTPException(status_code=403, detail=f"Dangerous command blocked: {d}")

    import subprocess
    try:
        result = subprocess.run(
            command if os.name == "nt" else ["sh", "-c", command],
            shell=(os.name == "nt"),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=_PROJECT_ROOT
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "output": result.stdout[:5000],
            "error": result.stderr[:2000] if result.stderr else None
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": -1, "output": "", "error": "Command timed out after 30s"}
    except Exception as e:
        return {"command": command, "returncode": -1, "output": "", "error": str(e)}


@app.get("/api/files")
def search_files(q: str = ""):
    """Search files for @file mention autocomplete."""
    files = []
    root = _PROJECT_ROOT
    q_lower = q.lower()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune directory list in place to avoid walking into unwanted trees
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".venv"}]
            
            rel = os.path.relpath(dirpath, root)
            if rel != ".":
                if any(part.startswith((".", "node_modules", "__pycache__", "venv", ".venv")) for part in rel.split(os.sep)):
                    continue
            for fname in filenames:
                full = os.path.join(rel, fname) if rel != "." else fname
                if q_lower in full.lower():
                    files.append(full)
                if len(files) >= 10:
                    break
            if len(files) >= 10:
                break
    except Exception:
        logger.warning("server:1661 : suppressed error", exc_info=True)
        pass
    return {"files": files[:10]}


# ── Voice API ─────────────────────────────────────────────────────────────────

def _voice_python_executable() -> str:
    candidates = [
        os.path.join(_PROJECT_ROOT, ".voice-venv", "Scripts", "python.exe"),
        os.path.join(_PROJECT_ROOT, ".voice-venv", "bin", "python"),
        os.path.join(_PROJECT_ROOT, ".venv", "Scripts", "python.exe"),
        os.path.join(_PROJECT_ROOT, ".venv", "bin", "python"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    import sys
    return sys.executable


def _voice_command_for_mode(mode: str, session_id: str = "default", owner_pid: int | None = None) -> list:
    python = _voice_python_executable()
    command = [python, "-c", "from voice.voice_chat import main; main()"]
    if mode == "manual":
        command.append("--manual")
    elif mode == "text":
        command.append("--text")
    command.extend(["--session-id", session_id])
    if owner_pid and owner_pid > 0:
        command.extend(["--owner-pid", str(owner_pid)])
    return command


def _kill_stray_voice_processes() -> None:
    try:
        import psutil
    except Exception:
        return

    current_pid = os.getpid()
    signatures = (
        "from voice.voice_chat import main; main()",
        "voice_chat.py",
    )

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if not cmdline:
                continue
            if any(signature in cmdline for signature in signatures):
                proc.terminate()
        except Exception:
            continue


def _voice_launch_options(mode: str) -> Dict[str, Any]:
    log_handle = open(_VOICE_LOG_PATH, "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        flags = CREATE_NO_WINDOW
    return {
        "stdout": log_handle,
        "stderr": log_handle,
        "stdin": subprocess.DEVNULL,
        "creationflags": flags,
        "log_handle": log_handle,
    }


def _voice_is_running() -> bool:
    global _VOICE_PROCESS
    if _VOICE_PROCESS is None:
        return False
    if _VOICE_PROCESS.poll() is None:
        return True
    _VOICE_PROCESS = None
    return False


def _strip_ansi(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def _tail_voice_log(max_chars: int = 24000) -> str:
    if not os.path.exists(_VOICE_LOG_PATH):
        return ""
    try:
        with open(_VOICE_LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def _voice_log_snapshot() -> Dict[str, str]:
    tail = _strip_ansi(_tail_voice_log()).replace("\r", "\n")
    phase_markers = {
        "ready": tail.rfind("[voice] Ready."),
        "starting": max(tail.rfind("[voice] Assistant ready."), tail.rfind("[voice] Manual voice mode.")),
        "listening": tail.rfind("[voice] listening..."),
        "waiting": tail.rfind("[voice] Waiting for speech..."),
        "hearing": tail.rfind("[voice] Hearing speech..."),
        "processing": tail.rfind("[voice] Processing..."),
        "speaking": max(tail.rfind("[voice] speaking..."), tail.rfind("[voice] Speaking reply...")),
        "paused": tail.rfind("[voice] paused."),
        "stopped": tail.rfind("[voice] stopped."),
        "error": max(tail.rfind("[voice-error]"), tail.rfind("[voice-warning]")),
    }
    phase = "idle"
    best_index = -1
    for candidate, index in phase_markers.items():
        if index > best_index:
            best_index = index
            phase = candidate

    transcript_matches = re.findall(r"You:\s*(.+)", tail)
    reply_matches = re.findall(r"NEXUS:\s*(.+)", tail)
    transcript_preview = transcript_matches[-1].strip() if transcript_matches else ""
    reply_preview = reply_matches[-1].strip() if reply_matches else ""
    reply_preview = re.sub(r"<thinking>.*?</thinking>", "", reply_preview, flags=re.DOTALL | re.IGNORECASE).strip()
    reply_preview = re.sub(r"</?thinking>", "", reply_preview, flags=re.IGNORECASE).strip()

    return {
        "phase": phase,
        "transcript_preview": transcript_preview,
        "reply_preview": reply_preview,
    }


def _voice_status_payload() -> Dict[str, Any]:
    running = _voice_is_running()
    snapshot = _voice_log_snapshot() if running else {
        "phase": "off",
        "transcript_preview": "",
        "reply_preview": "",
    }
    return {
        "running": running,
        "mode": _VOICE_MODE if running else "off",
        "pid": _VOICE_PROCESS.pid if running and _VOICE_PROCESS else None,
        "started_at": _VOICE_STARTED_AT if running else None,
        "log_path": _VOICE_LOG_PATH,
        "phase": snapshot["phase"],
        "transcript_preview": snapshot["transcript_preview"],
        "reply_preview": snapshot["reply_preview"],
    }


def _clean_visible_message_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\[NEXUS_BOOT\]:[^\n]*", "", cleaned)
    cleaned = re.sub(r"\[THINKING:[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?thinking>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("TASK_COMPLETE", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _sanitize_history_messages(messages: Any, session_id: str = "") -> list:
    if not isinstance(messages, list):
        return []
    events_by_run: Dict[str, list] = {}
    if session_id:
        for event in list_work_events(session_id, limit=1000):
            run_id = str(event.get("turn_id") or event.get("run_id") or "")
            if run_id:
                events_by_run.setdefault(run_id, []).append(event)

    def completed_content(events: list) -> str:
        for event in reversed(events):
            event_type = str(event.get("event_type") or event.get("type") or "")
            if event_type != "message.completed":
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            content = payload.get("content") or nested.get("content")
            if isinstance(content, str):
                return _clean_visible_message_text(content)
        return ""

    cleaned_messages = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "") or "")
        content = item.get("content", "")
        cleaned = {
            **item,
            "role": role,
            "content": _clean_visible_message_text(content) if role == "assistant" else str(content or ""),
        }
        if role == "assistant" and events_by_run:
            run_id = str(item.get("turn_id") or item.get("run_id") or "")
            activity = events_by_run.get(run_id, []) if run_id else []
            # Older transcripts predate the turn_id field. Match their saved
            # final response to the canonical terminal event so their real
            # activity timeline can still be replayed accurately.
            if not activity:
                for candidate_run, candidate_events in events_by_run.items():
                    if completed_content(candidate_events) == cleaned["content"]:
                        run_id, activity = candidate_run, candidate_events
                        break
            if activity:
                cleaned["turn_id"] = run_id
                cleaned["work_events"] = activity
        cleaned_messages.append(cleaned)
    return cleaned_messages


def _stop_voice_process() -> Dict[str, Any]:
    global _VOICE_PROCESS, _VOICE_MODE, _VOICE_STARTED_AT
    if _VOICE_PROCESS is not None:
        try:
            if _VOICE_PROCESS.poll() is None:
                _VOICE_PROCESS.terminate()
                _VOICE_PROCESS.wait(timeout=5)
        except Exception:
            try:
                _VOICE_PROCESS.kill()
            except Exception:
                logger.warning("server:1854 _stop_voice_process: suppressed error", exc_info=True)
                pass
        finally:
            _VOICE_PROCESS = None
    _kill_stray_voice_processes()
    _VOICE_MODE = "off"
    _VOICE_STARTED_AT = 0.0
    return _voice_status_payload()


@app.get("/api/voice/status")
def get_voice_status():
    return {"status": "success", **_voice_status_payload()}


@app.post("/api/voice/start")
async def start_voice(request: Request):
    global _VOICE_PROCESS, _VOICE_MODE, _VOICE_STARTED_AT
    data = await request.json()
    requested_mode = str(data.get("mode", "auto")).strip().lower()
    mode = requested_mode if requested_mode in {"auto", "manual", "text"} else "auto"
    session_id = str(data.get("session_id", "default")).strip()
    owner_pid = int(data.get("owner_pid") or 0)

    if _voice_is_running():
        return {"status": "success", **_voice_status_payload()}

    os.makedirs(os.path.dirname(_VOICE_LOG_PATH), exist_ok=True)
    _kill_stray_voice_processes()
    try:
        with open(_VOICE_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        logger.warning("server:1886 async start_voice: suppressed error", exc_info=True)
        pass
    command = _voice_command_for_mode(mode, session_id, owner_pid=owner_pid)
    launch = _voice_launch_options(mode)
    try:
        _VOICE_PROCESS = subprocess.Popen(
            command,
            cwd=_PROJECT_ROOT,
            stdout=launch["stdout"],
            stderr=launch["stderr"],
            stdin=launch["stdin"],
            creationflags=launch["creationflags"],
            shell=False,
        )
    except FileNotFoundError as exc:
        if launch.get("log_handle"):
            launch["log_handle"].close()
        raise HTTPException(status_code=500, detail=f"Voice Python runtime not found: {exc}") from exc
    except Exception as exc:
        if launch.get("log_handle"):
            launch["log_handle"].close()
        raise HTTPException(status_code=500, detail=f"Unable to start voice mode: {exc}") from exc

    await asyncio.sleep(1.0)
    if _VOICE_PROCESS.poll() is not None:
        tail = ""
        if os.path.exists(_VOICE_LOG_PATH):
            try:
                with open(_VOICE_LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    tail = f.read()[-2000:].strip()
            except Exception:
                tail = ""
        _VOICE_PROCESS = None
        _VOICE_MODE = "off"
        _VOICE_STARTED_AT = 0.0
        detail = tail or "Voice process exited immediately after launch."
        raise HTTPException(status_code=500, detail=detail)

    _VOICE_MODE = mode
    _VOICE_STARTED_AT = time.time()
    return {"status": "success", **_voice_status_payload()}


@app.post("/api/voice/stop")
def stop_voice():
    status = _stop_voice_process()
    return {"status": "success", **status}


@app.post("/api/multi_agent")
async def multi_agent(request: Request):
    """Trigger a multi-agent workflow."""
    data = await request.json()
    command = str(data.get("command", "")).lower()
    prompt = str(data.get("prompt", ""))

    # Simple echo for now — full implementation needs Workflow integration
    return {
        "status": "started",
        "command": command,
        "result": f"Multi-agent {command} started. Prompt: {prompt[:100]}",
        "note": "Full workflow engine integration required for live agent execution."
    }


@app.get("/api/engine/status")
def engine_status():
    try:
        from utils.engine_manager import get_engine_status, load_or_create_config
        return {
            "status": get_engine_status(),
            "config": load_or_create_config()
        }
    except ImportError:
        return {"status": "unavailable", "config": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/engine/config")
async def update_engine_config(request: Request):
    try:
        from utils.engine_manager import load_or_create_config, save_config
    except ImportError:
        raise HTTPException(status_code=501, detail="Engine manager not available")
    try:
        updates = await request.json()
        config = load_or_create_config()
        
        # Merge update dicts
        if "llama_cpp_params" in updates:
            for k, v in updates["llama_cpp_params"].items():
                config["llama_cpp_params"][k] = v
        if "system" in updates:
            for k, v in updates["system"].items():
                config["system"][k] = v
        if "default_model" in updates:
            config["default_model"] = updates["default_model"]
            
        save_config(config)
        return {"status": "success", "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/engine/compile")
async def compile_engine():
    try:
        from utils.engine_compiler import compile_llama_cpp
        res = compile_llama_cpp()
        return res
    except ImportError:
        raise HTTPException(status_code=501, detail="Engine compiler not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/engine/reload")
async def reload_local_engine(request: Request):
    try:
        from utils.engine_manager import reload_engine
    except ImportError:
        raise HTTPException(status_code=501, detail="Engine manager not available")
    try:
        data = await request.json()
        model_name = data.get("model")
        # Map model name to path if it is relative
        model_path = None
        if model_name:
            if os.path.isabs(model_name) and os.path.exists(model_name):
                model_path = model_name
            else:
                model_path = os.path.join(_PROJECT_ROOT, "models", "local", model_name)
                
        status = reload_engine(model_path)
        return {"status": "success", "engine": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

_active_train_process = None

@app.post("/api/engine/train")
async def train_local_engine(request: Request):
    global _active_train_process
    
    # Check if already running
    if _active_train_process and _active_train_process.poll() is None:
        return {"status": "running", "message": "Self-improvement training is already in progress."}
        
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    steps = data.get("steps", 50)
    
    # Launch background training process to avoid blocking
    import platform
    import subprocess
    import sys
    
    train_script = os.path.join(_PROJECT_ROOT, "evolution", "self_improvement.py")
    cmd = [sys.executable, train_script, str(steps)]
    
    creation_flags = 0
    if platform.system() == "Windows":
        creation_flags = subprocess.CREATE_NO_WINDOW
        
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags
    )
    _active_train_process = proc
    
    return {"status": "started", "pid": proc.pid, "message": f"Self-improvement training session started with {steps} steps."}

@app.get("/api/engine/train/status")
def train_status():
    global _active_train_process
    
    status_file = os.path.join(_PROJECT_ROOT, "config", "self_improvement_status.json")
    status = {"status": "idle", "message": "No training has been run yet."}
    
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                status = json.load(f)
        except Exception:
            logger.warning("server:2071 train_status: suppressed error", exc_info=True)
            pass
            
    # Check if process is actively running
    is_running = _active_train_process and _active_train_process.poll() is None
    if is_running:
        status["is_running"] = True
        if status.get("status") in ("completed", "failed"):
            # Omit completed/failed states while training is active
            status["status"] = "training"
    else:
        status["is_running"] = False
        if _active_train_process:
            exit_code = _active_train_process.poll()
            if exit_code != 0 and status.get("status") not in ("completed", "failed"):
                status["status"] = "failed"
                status["error"] = f"Training process terminated unexpectedly with code {exit_code}."
                status["message"] = f"Failed: Process exited with code {exit_code}."
                
    return status



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

