import asyncio
import concurrent.futures
import inspect
import ipaddress
import json
import logging
import os
import queue
import re
import shutil
import stat
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from collections import deque
from contextlib import contextmanager
from io import BytesIO
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import yaml

logger = logging.getLogger("NEXUS_API")
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# 🌌 [NEXUS_PATH_CORE]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Keep GUI-launched API workers consistent with the standalone server.
load_dotenv(os.path.join(_ROOT, ".env"), override=False)
load_dotenv(os.path.join(_ROOT, "configure", ".env"), override=False)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from nexus.events import CanonicalEvent
from nexus.run_context import list_run_contexts, load_run_context
from nexus.session_store import atomic_write_json, session_write_lock
from nexus.work_items import (
    pending_work_item_projection_failures,
    project_work_item_event,
    record_work_item_projection_failure,
    replay_work_item_event_log,
)
from nexus.control_plane import project_plan_event
from nexus.runtime import (
    build_chat_request,
    build_resume_prompt,
)
from nexus.task_workflow import complete_task_workflow, start_task_workflow
from nexus.runtime import (
    safe_session_id as runtime_safe_session_id,
)
from nexus.runtime import (
    session_file_path as runtime_session_file_path,
)
from nexus.main_agent import NexusLoop
from nexus.common.context_scrubber import StreamingContextScrubber

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
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_SHOW_CHAT_THINKING = os.environ.get("NEXUS_CHAT_SHOW_THINKING", "false").lower() in {"1", "true", "yes", "on"}
_SANDBOX_TIER = os.environ.get("NEXUS_SANDBOX_TIER", "normal").strip().lower() or "normal"
_SANDBOX_ROOT = os.path.abspath(os.environ.get("NEXUS_SANDBOX_ROOT", os.path.join(_ROOT, "workspace")))

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
_WORK_EVENT_LOCK = threading.Lock()
_WORK_EVENT_SEQUENCES: Dict[str, int] = {}
_WORK_EVENT_MAX_RECORDS = max(100, int(os.environ.get("NEXUS_WORK_EVENT_MAX_RECORDS", "10000")))
_WORK_EVENT_MAX_BYTES = max(1024 * 1024, int(os.environ.get("NEXUS_WORK_EVENT_MAX_BYTES", str(50 * 1024 * 1024))))
_WORK_EVENT_CACHE: Dict[str, Tuple[Tuple[int, int], List[Dict[str, Any]], int]] = {}
_WORK_EVENT_CACHE_LOCK = threading.RLock()
_SOURCE_LIBRARY_LOCK = threading.RLock()
_PROVIDER_CONFIG_LOCK = threading.RLock()


@contextmanager
def _interprocess_event_lock(path: str):
    """Serialize one GUI event stream across dashboard worker processes."""
    lock_path = f"{path}.lock.sqlite"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS event_mutex (id INTEGER PRIMARY KEY CHECK (id = 1))")
        connection.execute("INSERT OR IGNORE INTO event_mutex(id) VALUES (1)")
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def refresh_provider_runtime() -> str:
    """Reload provider.yml and return the canonical default provider."""
    try:
        from configure.config_loader import NexusConfigLoader
        loader = NexusConfigLoader()
        loader.reload()
        provider_cfg = loader.get("provider", {})
        default_provider = ""
        if isinstance(provider_cfg, dict):
            default_provider = str(provider_cfg.get("default_provider") or "").strip()
        try:
            from models.providers.core.factory import NexusProviderFactory
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
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
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
    def sequence_key(event: Dict[str, Any]) -> int:
        try:
            return max(0, int(event.get("sequence") or 0))
        except (AttributeError, TypeError, ValueError):
            return 0
    retained.sort(key=sequence_key)
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


def _session_work_event_paths(session_id: str) -> List[str]:
    """Return canonical plus pre-normalization event-log paths for reads."""
    canonical = work_events_path(session_id)
    raw = str(session_id or "default")
    legacy_name = re.sub(r"[^A-Za-z0-9_.-]", "_", raw.strip())[:120] or "default"
    legacy = os.path.abspath(os.path.join(_WORK_EVENTS_DIR, f"{legacy_name}.jsonl"))
    return [canonical] if legacy == canonical or not os.path.isfile(legacy) else [canonical, legacy]


def _session_work_events(session_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for path in _session_work_event_paths(session_id):
        events.extend(_cached_work_events(path)[0])
    events.sort(key=lambda event: (_safe_event_sequence(event), str(event.get("created_at") or "")))
    return events


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


def _next_work_event_sequence_unlocked(path: str) -> int:
    """Allocate a sequence after the per-stream interprocess lock is held."""
    last = _WORK_EVENT_SEQUENCES.get(path, 0)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    last = max(last, _safe_event_sequence(event))
                except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    _WORK_EVENT_SEQUENCES[path] = last + 1
    return _WORK_EVENT_SEQUENCES[path]


def _next_work_event_sequence(path: str) -> int:
    """Return a process-safe, restart-safe sequence for one persisted stream."""
    with _interprocess_event_lock(path):
        return _next_work_event_sequence_unlocked(path)


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
    from security.core.auth import validate_dashboard_token
    supplied = request.headers.get("x-nexus-token", "")
    if not validate_dashboard_token(supplied):
        raise HTTPException(status_code=401, detail="Invalid dashboard token")
    if _LOCAL_ONLY and request.client and request.client.host not in _LOCAL_CLIENTS:
        raise HTTPException(status_code=403, detail="Dashboard config writes are local-only")


def require_local_runtime_control(request: Request) -> None:
    """Runtime controls are available to the local GUI without a dashboard token."""
    if _LOCAL_ONLY and request.client and request.client.host not in _LOCAL_CLIENTS:
        raise HTTPException(status_code=403, detail="Runtime controls are local-only")


def _check_gui_terminal_permission(sid: str, turn_id: str, command: str):
    from security.permissions import PermissionMode, PermissionSystem

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
            context={
                "session_id": sid,
                "turn_id": turn_id,
                "surface": "gui",
            },
        )
    finally:
        permissions.set_mode(previous_mode)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    if _LOCAL_ONLY and client not in _LOCAL_CLIENTS:
        audit_event(request, "blocked", "non-local client")
        return JSONResponse({"detail": "Dashboard is local-only"}, status_code=403)

    # When the GUI is intentionally exposed beyond loopback, local-only
    # network placement is no longer a security boundary. Require the same
    # dashboard authentication used by the canonical API. Health remains a
    # public liveness probe so a reverse proxy can monitor the process.
    if not _LOCAL_ONLY and request.url.path != "/api/health":
        from security.core.auth import check_auth
        if check_auth(request) is None:
            audit_event(request, "blocked", "not authenticated")
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

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
    return runtime_safe_session_id(session_id)


def session_file_path(session_id: str, suffix: str = ".json") -> str:
    sessions_dir = os.path.join(_ROOT, "logs", "sessions")
    try:
        return runtime_session_file_path(sessions_dir, session_id, suffix)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id")


def safe_upload_path(filename: str) -> str:
    raw_name = str(filename or "upload.bin").replace("\\", "/")
    parts = [part for part in raw_name.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="Invalid upload filename")
    safe_parts = [re.sub(r"[^A-Za-z0-9_. -]", "_", part).strip() or "upload" for part in parts]
    upload_root = os.path.realpath(os.path.abspath(_UPLOAD_DIR))
    path = os.path.realpath(os.path.abspath(os.path.join(upload_root, *safe_parts)))
    try:
        inside = os.path.commonpath([upload_root, path]) == upload_root
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=400, detail="Invalid upload filename")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _write_uploaded_bytes_sync(path: str, content: bytes) -> None:
    """Write an already bounded upload outside the async request thread."""
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so URL validation cannot be bypassed by a second hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover - urllib calls this on redirect
        raise HTTPException(status_code=403, detail="Redirects are not allowed for website imports")


def _validate_public_source_url(raw_url: str):
    """Validate every resolved address before fetching an external source."""
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Enter a valid public http(s) URL")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Could not resolve URL")
    if not addresses:
        raise HTTPException(status_code=400, detail="Could not resolve URL")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            raise HTTPException(status_code=403, detail="URL resolved to an invalid address")
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_unspecified, ip.is_reserved)):
            raise HTTPException(status_code=403, detail="Private/internal URLs are not allowed")
    return parsed


def _fetch_website_source_sync(raw_url: str, parsed: Any) -> tuple[str, str]:
    """Fetch and extract a bounded website source outside the event loop."""
    req = urllib.request.Request(
        raw_url, headers={"User-Agent": "NEXUS-AI-Source-Importer/1.0"}
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    with opener.open(req, timeout=12) as response:
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
    return text[:_MAX_UPLOAD_BYTES], title


def load_source_library() -> List[Dict[str, Any]]:
    with _SOURCE_LIBRARY_LOCK:
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
    with _SOURCE_LIBRARY_LOCK:
        os.makedirs(os.path.dirname(_SOURCE_LIBRARY_PATH), exist_ok=True)
        temporary = f"{_SOURCE_LIBRARY_PATH}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
                json.dump(sources, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, _SOURCE_LIBRARY_PATH)
        finally:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass


def upsert_source_library(item: Dict[str, Any]) -> Dict[str, Any]:
    with _SOURCE_LIBRARY_LOCK, _interprocess_event_lock(_SOURCE_LIBRARY_PATH):
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


def _index_source_sync(rel_path: str) -> None:
    """Run potentially expensive RAG indexing outside an async handler."""
    get_loop("default").rag.index_workspace(file_path=rel_path)


def update_source_library(source_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    with _SOURCE_LIBRARY_LOCK, _interprocess_event_lock(_SOURCE_LIBRARY_PATH):
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
    with _SOURCE_LIBRARY_LOCK, _interprocess_event_lock(_SOURCE_LIBRARY_PATH):
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
    root = os.path.realpath(os.path.abspath(_ROOT))
    path = os.path.realpath(os.path.abspath(value))
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(status_code=400, detail="Path is outside the NEXUS workspace")
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return path


def _safe_artifact_file_path(root: str, candidate: str) -> str | None:
    """Return an artifact file only when it is a real, in-root file."""
    root_path = os.path.realpath(os.path.abspath(root))
    candidate_path = os.path.abspath(candidate)
    if os.path.islink(candidate_path):
        return None
    resolved = os.path.realpath(candidate_path)
    try:
        inside = os.path.commonpath([root_path, resolved]) == root_path
    except ValueError:
        inside = False
    return resolved if inside and os.path.isfile(resolved) else None


def work_events_path(session_id: str) -> str:
    sid = safe_session_id(session_id)
    path = os.path.abspath(os.path.join(_WORK_EVENTS_DIR, f"{sid}.jsonl"))
    if os.path.commonpath([os.path.abspath(_WORK_EVENTS_DIR), path]) != os.path.abspath(_WORK_EVENTS_DIR):
        raise HTTPException(status_code=400, detail="Invalid session id")
    return path


def _safe_event_sequence(event: Dict[str, Any], default: int = 0) -> int:
    """Normalize untrusted persisted sequence values for all read paths."""
    try:
        value = int(event.get("sequence") or default)
    except (AttributeError, TypeError, ValueError):
        return max(0, int(default or 0))
    return max(0, value)


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
            event["path"] = os.path.relpath(file_path, _ROOT)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                event["preview"] = f.read(20000)
        except Exception as exc:
            event["preview_error"] = str(exc)
    os.makedirs(_WORK_EVENTS_DIR, exist_ok=True)
    path = work_events_path(session_id)
    with _WORK_EVENT_LOCK, _interprocess_event_lock(path):
        if event.get("sequence") is not None:
            event["source_sequence"] = event["sequence"]
        sequence = _next_work_event_sequence_unlocked(path)
        canonical = CanonicalEvent.from_work_event(event, event["session_id"], sequence).to_dict()
        event["legacy_type"] = event.get("type")
        event["legacy_status"] = event.get("status")
        event.update(canonical)
        # Compatibility aliases remain during the adapter migration; all new
        # records still persist the complete canonical envelope above.
        event["id"] = event["event_id"]
        event["session_id"] = event["conversation_id"]
        event["created_at"] = event["timestamp"]
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        _invalidate_work_event_cache(path)
        _compact_work_event_log_if_needed(path)
        
    if hasattr(_THREAD_LOCAL, "appended_events"):
        _THREAD_LOCAL.appended_events.append(event)

    # Keep the legacy GUI API aligned with the canonical server append path.
    # The projector is append-free and therefore cannot recursively create
    # events; events without explicit task/run identity are harmless no-ops.
    try:
        project_work_item_event(root=_ROOT, session_id=event["conversation_id"], event=event)
        project_plan_event(root=_ROOT, session_id=event["conversation_id"], event=event)
    except Exception as exc:
        logger.debug("Could not project GUI work event onto WorkItem", exc_info=True)
        record_work_item_projection_failure(
            event_log_path=work_events_path(event["conversation_id"]),
            event=event,
            error=exc,
        )
        
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
            from nexus.runtime.kernel import get_nexus_kernel
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
    from extensions.tools.built_in.planning.scripts.planning import plan_transaction

    workspace_dir = os.path.join(_ROOT, "workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    todo_path = os.path.abspath(os.path.join(workspace_dir, "todo.md"))
    if os.path.commonpath([os.path.abspath(workspace_dir), todo_path]) != os.path.abspath(workspace_dir):
        raise HTTPException(status_code=400, detail="Invalid todo path")
    with plan_transaction(_ROOT):
        temp_path = f"{todo_path}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, todo_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
    return os.path.relpath(todo_path, _ROOT)


def workflow_needs_plan(prompt: str) -> bool:
    # Disable automatic plan generation/auto-creation of phases by default
    return False


def clear_workspace_todo_plan() -> None:
    from extensions.tools.built_in.planning.scripts.planning import plan_transaction

    try:
        with plan_transaction(_ROOT):
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
    return start_task_workflow(
        session_id,
        prompt,
        turn_id,
        prompt_requests_resume=prompt_requests_resume,
        latest_snapshot=latest_todo_snapshot,
        append_todo_events=append_todo_events_from_content,
        clear_plan=clear_workspace_todo_plan,
    )


def complete_chat_workflow(session_id: str, prompt: str, turn_id: str = "", status: str = "done") -> None:
    complete_task_workflow(
        session_id,
        prompt,
        turn_id,
        status,
        safe_session_id=safe_session_id,
        list_events=lambda sid, tid: list_work_events(sid, limit=1000, active_turn_id=tid),
        append_event=append_work_event,
        write_plan=write_workspace_todo_plan,
    )


def list_work_events(session_id: str, limit: int = 200, active_turn_id: str = "") -> List[Dict[str, Any]]:
    path = work_events_path(session_id)
    raw_events = _session_work_events(session_id)

    _HIDDEN_TARGETS = {
        "prompt_files",
        "CRITICAL PREVENTIVE VACCINE: internal",
    }
    filtered_events = []
    latest_turn_id = str(active_turn_id or "")
    for evt in raw_events:
        if str(evt.get("visibility", "")).lower() == "internal":
            continue
        if evt.get("target") in _HIDDEN_TARGETS:
            continue
        if evt.get("kind") == "test" and evt.get("target") == "CRITICAL PREVENTIVE VACCINE: internal":
            continue
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
            if not plan:
                return filtered_events
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

    # Event IDs are lifecycle records: keep the newest payload while retaining
    # the position where the event first appeared. Sorting opaque IDs here used
    # to scramble the real execution timeline on every replay.
    dedupe_order: List[str] = []
    latest_by_key: Dict[str, Dict[str, Any]] = {}
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
        if dedupe_key not in latest_by_key:
            dedupe_order.append(dedupe_key)
        latest_by_key[dedupe_key] = event
    deduped = [latest_by_key[k] for k in dedupe_order]

    return deduped[-max(1, min(limit, 1000)):]


def replay_work_events_after(session_id: str, after_sequence: int, limit: int = 200) -> List[Dict[str, Any]]:
    """Replay the append-only canonical log without lifecycle-state dedupe."""
    hidden_targets = {
        "prompt_files",
        "CRITICAL PREVENTIVE VACCINE: internal",
    }
    events: List[Dict[str, Any]] = []
    path = work_events_path(session_id)
    raw_events = _session_work_events(session_id)
    for event in raw_events:
        if str(event.get("visibility", "")).lower() == "internal":
            continue
        if event.get("target") in hidden_targets:
            continue
        if event.get("kind") == "test" and event.get("target") in hidden_targets:
            continue
        if _safe_event_sequence(event) > after_sequence:
            events.append(event)
            if len(events) >= max(1, min(limit, 1000)):
                break
    return events[:max(1, min(limit, 1000))]


def work_event_run_summary(session_id: str, run_id: str) -> Dict[str, Any]:
    """Small replay index for a durable run without sending the whole log."""
    raw_events = _session_work_events(session_id)
    statuses: Dict[str, int] = {}
    kinds: Dict[str, int] = {}
    event_count = 0
    last_sequence = 0
    terminal_event = ""
    for event in raw_events:
        if str(event.get("turn_id") or event.get("run_id") or "") != str(run_id):
            continue
        if str(event.get("visibility") or "public").lower() == "internal":
            continue
        event_count += 1
        status = str(event.get("status") or "unknown")
        kind = str(event.get("kind") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        kinds[kind] = kinds.get(kind, 0) + 1
        try:
            last_sequence = max(last_sequence, int(event.get("sequence") or 0))
        except (TypeError, ValueError):
            pass
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type.startswith("run.") and (
            status in {"success", "failed", "cancelled", "canceled", "timed_out", "error"}
            or event_type == "run.timed_out"
        ):
            terminal_event = event_type
    return {
        "event_count": event_count,
        "last_sequence": last_sequence,
        "statuses": statuses,
        "kinds": kinds,
        "terminal_event": terminal_event,
    }


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
    from nexus.common.session_bus import sync_loop_from_disk

    session_id = safe_session_id(session_id)
    if session_id not in _LOOPS:
        loop = NexusLoop(root_dir=_ROOT)
        _apply_sandbox_tier(loop)
        loop.load_memory(session_id)
        # The loop publishes structured lifecycle/tool records through this
        # adapter. Without the sink, only brittle text-marker parsing reached
        # persistence and real tool events were silently lost.
        loop.work_event_sink = lambda payload, sid=session_id: append_work_event(sid, payload)
        _LOOPS[session_id] = loop
    else:
        sync_loop_from_disk(_LOOPS[session_id])
    return _LOOPS[session_id]


def _apply_sandbox_tier(loop: NexusLoop) -> None:
    """Keep every active GUI session on the user-selected execution tier."""
    from sandbox.sandbox_manager import SandboxTier

    loop.sandbox_tier = SandboxTier(_SANDBOX_TIER)
    sandbox = getattr(loop, "sandbox", None)
    if sandbox is None:
        ensure_sandbox = getattr(loop, "_sandbox", None)
        sandbox = ensure_sandbox() if callable(ensure_sandbox) else getattr(getattr(loop, "runtime", None), "sandbox", None)
    if sandbox is None:
        raise RuntimeError("Sandbox is unavailable; refusing to start a GUI session without execution isolation")
    sandbox.tier = loop.sandbox_tier
    sandbox.root = _SANDBOX_ROOT


class _CancellableStreamQueue(queue.Queue):
    """Bound stream queue that releases producers when a client disconnects."""

    def __init__(self, stop_event: threading.Event, maxsize: int = 256):
        super().__init__(maxsize=maxsize)
        self._stop_event = stop_event

    def put(self, item, block=True, timeout=None):
        if not block:
            if self._stop_event.is_set():
                return False
            super().put(item, block=False)
            return True
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while not self._stop_event.is_set():
            wait = 0.25
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.monotonic()))
                if wait <= 0:
                    raise queue.Full
            try:
                super().put(item, block=True, timeout=wait)
                return True
            except queue.Full:
                continue
        return False


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

@app.get("/api/sessions/active")
def get_active_session():
    from nexus.common.session_bus import get_active_session

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
    from nexus.common.session_bus import set_active_session_id

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
            except Exception as e:
                logger.warning(f"Failed to read session file {path}: {e}")
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
    from nexus.common.session_bus import set_active_session_id

    new_id = f"session_{int(time.time())}"
    clear_workspace_todo_plan()
    loop = get_loop(new_id)
    loop.save_memory()
    set_active_session_id(_ROOT, new_id, source="gui")
    return {"id": new_id, "title": "New Chat"}

@app.post("/api/sessions/load")
async def load_session(request: Request):
    from nexus.common.session_bus import set_active_session_id

    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    set_active_session_id(_ROOT, sid, source=str(data.get("source", "gui")))
    loop = get_loop(sid)
    # Chat text is saved in the session memory while tool/command activity is
    # stored in the durable work-event log. Reattach each chronological run to
    # its assistant reply so the GUI can show the same work cards after reload.
    history = [dict(message) for message in loop.memory if isinstance(message, dict)]
    events_by_turn: Dict[str, List[Dict[str, Any]]] = {}
    turn_order: List[str] = []
    for event in list_work_events(sid, limit=1000):
        if str(event.get("visibility", "public")).lower() == "internal":
            continue
        turn_id = str(event.get("turn_id") or event.get("run_id") or "")
        if not turn_id:
            continue
        if turn_id not in events_by_turn:
            events_by_turn[turn_id] = []
            turn_order.append(turn_id)
        events_by_turn[turn_id].append(event)

    assistant_index = 0
    for message in history:
        if str(message.get("role", "")) != "assistant":
            continue
        if assistant_index < len(turn_order):
            message["work_events"] = events_by_turn[turn_order[assistant_index]]
        assistant_index += 1
    return {"status": "success", "id": loop.session_id, "history": history}

def _clear_session_files(session_id: str) -> bool:
    """Reset or remove persisted session data and in-memory loop cache."""
    path = session_file_path(session_id)
    meta_path = session_file_path(session_id, ".meta")

    clear_workspace_todo_plan()

    # Use the same lock/atomic replacement protocol as V5 and MemoryManager.
    # This prevents a GUI clear from racing a server/V5 transcript save.
    with session_write_lock(path):
        existed = os.path.exists(path) or os.path.exists(meta_path) or session_id in _LOOPS
        atomic_write_json(path, [])
        atomic_write_json(meta_path, {"title": "New Chat"})
        if session_id in _LOOPS:
            _LOOPS[session_id].memory = []

    return existed


def _delete_session_files(session_id: str) -> bool:
    """Delete one non-default session under the shared persistence lock."""
    path = session_file_path(session_id)
    meta_path = session_file_path(session_id, ".meta")
    with session_write_lock(path):
        existed = os.path.exists(path) or os.path.exists(meta_path) or session_id in _LOOPS
        if not existed:
            return False
        for candidate in (path, meta_path):
            try:
                os.remove(candidate)
            except FileNotFoundError:
                pass
        _LOOPS.pop(session_id, None)
        return True


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

    if not _delete_session_files(session_id):
        return {"status": "error", "id": session_id, "deleted": False, "message": "Session not found"}
    return {"status": "success", "id": session_id, "deleted": True}

@app.post("/api/sessions/rename")
async def rename_session(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    new_title = str(data.get("title", "")).strip()[:120]
    path = session_file_path(sid)
    if os.path.exists(path):
        meta_path = session_file_path(sid, ".meta")
        await asyncio.to_thread(_write_session_title_sync, meta_path, new_title)
        return {"status": "success"}
    return {"status": "error"}


def _write_session_title_sync(meta_path: str, title: str) -> None:
    """Persist GUI session metadata atomically outside the async loop."""
    directory = os.path.dirname(meta_path) or "."
    os.makedirs(directory, exist_ok=True)
    session_path = os.path.join(directory, f"{os.path.basename(meta_path)[:-5]}.json")
    with session_write_lock(session_path):
        atomic_write_json(meta_path, {"title": title})


def _session_title_needs_write_sync(meta_path: str) -> bool:
    """Read session metadata outside the async chat request path."""
    if not os.path.exists(meta_path):
        return True
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("title") == "New Chat" if isinstance(meta, dict) else True
    except Exception:
        return True

@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Invalid chat JSON: {exc}"},
            status_code=400,
    )
    from nexus.common.session_bus import set_active_session_id

    default_p = refresh_provider_runtime()
    try:
        chat_request = build_chat_request(data, default_provider=default_p, default_source="gui")
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "message": str(exc)},
            status_code=400,
        )
    prompt = chat_request.prompt
    sid = chat_request.session_id
    turn_id = chat_request.turn_id
    set_active_session_id(_ROOT, sid, source=chat_request.source or "gui")
    loop = get_loop(sid)
    if bool(getattr(loop, "is_running", False)):
        return JSONResponse(
            {"status": "error", "message": "A run is already active for this session"},
            status_code=409,
    )
    loop.reset()
    
    # Normalize provider
    provider = chat_request.provider
    model = chat_request.model or str(getattr(loop, "model", "") or "").strip()
    max_tokens = chat_request.max_tokens
    reasoning_effort = str(data.get("reasoning_effort") or "medium").strip().lower()
    if reasoning_effort in {"minimal", "low", "medium", "high", "extra_high", "max", "ultra"}:
        loop.reasoning_effort = reasoning_effort
    # The terminal client historically sent show_thoughts while the GUI API
    # expected show_thinking.  Accept both names as the same user setting.
    show_thinking = bool(data.get("show_thinking", data.get("show_thoughts", _SHOW_CHAT_THINKING)))
    try:
        chat_timeout = max(
            1.0,
            min(float(data.get("timeout_seconds") or os.environ.get("NEXUS_CHAT_IDLE_TIMEOUT", "300")), 3600.0),
        )
    except (TypeError, ValueError):
        chat_timeout = 300.0
    
    # Auto-title session if new
    meta_path = session_file_path(sid, ".meta")
    should_write = await asyncio.to_thread(_session_title_needs_write_sync, meta_path)
    if should_write:
        try:
            await asyncio.to_thread(_write_session_title_sync, meta_path, prompt[:50])
        except Exception as e:
            print(f"[API_ERROR]: Failed to write session meta: {e}")

    resume_todo_context = ""
    try:
        resume_todo_context = await asyncio.to_thread(start_chat_workflow, sid, prompt, turn_id)
    except Exception as e:
        print(f"[API_ERROR]: Failed to start chat workflow events: {e}")

    effective_prompt = build_resume_prompt(prompt, resume_todo_context)

    async def event_generator():
        completed = False
        partial_response = []
        deadline_at = time.monotonic() + chat_timeout
        legacy_raw_stream = str(data.get("stream_format") or "").lower() in {"raw", "legacy"}
        stop_event = threading.Event()
        stream_queue: "queue.Queue[tuple[str, Any]]" = _CancellableStreamQueue(stop_event)
        previous_work_event_sink, active_work_event_sink = bind_live_work_event_sink(loop, sid, turn_id, stream_queue)
        last_activity_at = time.monotonic()
        thought_events: list[tuple[str, dict[str, str]]] = []
        thought_open = False

        # Providers may stream private reasoning in <thinking> spans.  Keep
        # that text out of the chat, while truthfully reporting that a real
        # reasoning span started/ended so the TUI can show a timed Thought row.
        def on_thinking_delta(_: str) -> None:
            nonlocal thought_open
            if show_thinking and not thought_open:
                thought_open = True
                thought_events.append(("thinking", {"delta": "Reasoning in progress. Expand this record after completion for the safe activity summary."}))

        def on_thinking_done() -> None:
            nonlocal thought_open
            if thought_open:
                thought_events.append(("thinking_done", {}))
                thought_open = False

        scrubber = StreamingContextScrubber(
            on_thinking_delta=on_thinking_delta,
            on_thinking_done=on_thinking_done,
        )

        def stream_frame(event: str, payload: Any) -> str:
            return encode_chat_stream_frame(event, payload, legacy=legacy_raw_stream)

        def _run_async_stream(async_gen, out_queue: "queue.Queue[tuple[str, str]]") -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                async def _consume() -> None:
                    async for chunk in async_gen:
                        out_queue.put(("chunk", chunk or ""))
                loop.run_until_complete(_consume())
            except Exception as exc:
                out_queue.put(("error", str(exc)))

        def run_loop_stream() -> None:
            try:
                result = loop.stream_run(
                    effective_prompt,
                    provider=provider,
                    model=model,
                    max_tokens=max_tokens,
                    turn_id=turn_id,
                    deadline_seconds=chat_timeout,
                )
                if inspect.isasyncgen(result):
                    _run_async_stream(result, stream_queue)
                elif inspect.isgenerator(result) or hasattr(result, "__next__"):
                    for stream_chunk in result:
                        stream_queue.put(("chunk", stream_chunk or ""))
                stream_queue.put(("done", ""))
            except Exception as stream_error:
                stream_queue.put(("error", str(stream_error)))

        producer_thread = threading.Thread(target=run_loop_stream, daemon=True)
        producer_thread.start()

        try:
            while True:
                try:
                    remaining = max(0.05, deadline_at - time.monotonic())
                    kind, chunk = await asyncio.to_thread(
                        stream_queue.get, True, min(15.0, remaining)
                    )
                except queue.Empty:
                    if time.monotonic() >= deadline_at:
                        request_abort = getattr(loop, "request_abort", None)
                        if callable(request_abort):
                            request_abort(turn_id, "deadline_exceeded")
                        raise TimeoutError(f"Chat run timed out after {chat_timeout:.0f} seconds")
                    yield stream_frame("heartbeat", {"timestamp": time.time(), "status": "running"})
                    continue

                if kind == "done":
                    trailing_chunk = scrubber.flush()
                    while thought_events:
                        event_name, payload = thought_events.pop(0)
                        yield stream_frame(event_name, payload)
                    if trailing_chunk:
                        visible_chunk = attach_work_events_to_chunk(sid, filter_chat_chunk(trailing_chunk), turn_id=turn_id)
                        if visible_chunk:
                            yield stream_frame("message", {"content": visible_chunk})
                    completed = True
                    break
                if kind == "error":
                    raise RuntimeError(chunk)
                if kind == "event":
                    yield stream_frame("work_event", {"event": chunk})
                    continue

                if isinstance(chunk, dict):
                    if chunk.get("type") != "content":
                        continue
                    chunk = str(chunk.get("data") or "")

                partial_response.append(chunk)
                visible_chunk = scrubber.feed(str(chunk))
                while thought_events:
                    event_name, payload = thought_events.pop(0)
                    yield stream_frame(event_name, payload)
                visible_chunk = filter_chat_chunk(visible_chunk)
                visible_chunk = attach_work_events_to_chunk(sid, visible_chunk, turn_id=turn_id)
                if visible_chunk:
                    yield stream_frame("message", {"content": visible_chunk})
        except Exception as e:
            print(f"[CHAT_ERROR]: {e}")
            error_text = f"\nNEXUS chat error: {str(e)}"
            partial_response.append(error_text)
            try:
                complete_chat_workflow(sid, prompt, turn_id=turn_id, status="failed")
            except Exception:
                pass
            yield stream_frame("error", {"message": error_text})
        finally:
            stop_event.set()
            if not completed:
                request_abort = getattr(loop, "request_abort", None)
                if callable(request_abort):
                    try:
                        request_abort(turn_id, "client_disconnect")
                    except Exception:
                        pass
            if loop.work_event_sink is active_work_event_sink:
                loop.work_event_sink = previous_work_event_sink
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
            if producer_thread.is_alive():
                await asyncio.to_thread(producer_thread.join, 1.0)
            if completed:
                yield stream_frame("done", "[DONE]")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/chat/{session_id}/cancel")
def cancel_chat(session_id: str, turn_id: str = ""):
    """Propagate cancellation into the active loop and canonical event log."""
    sid = safe_session_id(session_id)
    loop = _LOOPS.get(sid)
    if loop is None:
        raise HTTPException(status_code=404, detail="Active session not found")
    run_id = str(turn_id or getattr(loop, "_current_turn_id", "") or "")
    if not run_id:
        raise HTTPException(status_code=409, detail="No active run id available")
    request_abort = getattr(loop, "request_abort", None)
    if callable(request_abort):
        if not request_abort(run_id):
            raise HTTPException(status_code=409, detail="Requested run is no longer active")
    else:
        try:
            loop.abort(turn_id=run_id)
        except TypeError:
            # Preserve compatibility with legacy loop adapters whose abort()
            # method predates per-run cancellation.
            loop.abort()
    # The active loop owns canonical lifecycle persistence. Returning the
    # immediate acknowledgement here avoids appending a duplicate run terminal.
    event = {
        "id": f"run_{run_id}", "type": "run.cancelled", "event_type": "run.cancelled", "run_id": run_id,
        "turn_id": run_id, "kind": "run", "title": "Run cancelled", "status": "cancelled",
        "visibility": "public",
    }
    return {"status": "cancelled", "run_id": run_id, "event": event}

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    saved_paths = []
    source_items = []
    for file in files:
        file_path = safe_upload_path(file.filename)
        total = 0
        content = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload too large")
            content.extend(chunk)
        await asyncio.to_thread(_write_uploaded_bytes_sync, file_path, bytes(content))
        saved_paths.append(file_path)
        rel_path = os.path.relpath(file_path, _ROOT).replace("\\", "/")
        source_items.append(await asyncio.to_thread(upsert_source_library, {
            "id": f"file_{uuid.uuid4().hex[:10]}",
            "name": os.path.basename(file_path),
            "type": "File",
            "path": rel_path,
            "checked": True,
        }))
        try:
            await asyncio.to_thread(_index_source_sync, rel_path)
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
    parsed = await asyncio.to_thread(_validate_public_source_url, raw_url)

    try:
        text, title = await asyncio.to_thread(
            _fetch_website_source_sync, raw_url, parsed
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import website: {exc}")

    safe_host = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed.netloc).strip("._") or "website"
    file_name = f"web_{safe_host}_{uuid.uuid4().hex[:8]}.txt"
    file_path = safe_upload_path(file_name)
    await asyncio.to_thread(
        _write_uploaded_bytes_sync, file_path, text.encode("utf-8")
    )
    rel_path = os.path.relpath(file_path, _ROOT).replace("\\", "/")
    source = await asyncio.to_thread(upsert_source_library, {
        "id": f"web_{uuid.uuid4().hex[:10]}",
        "name": str(data.get("name") or title or parsed.netloc)[:180],
        "type": "Website",
        "path": rel_path,
        "url": raw_url,
        "checked": True,
    })
    try:
        await asyncio.to_thread(_index_source_sync, rel_path)
    except Exception as index_error:
        print(f"[SOURCE_WARN]: Could not index website {rel_path}: {index_error}")
    return {"status": "success", "source": source}


@app.patch("/api/sources/{source_id}")
async def patch_source(source_id: str, request: Request):
    data = await request.json()
    source = await asyncio.to_thread(update_source_library, source_id, data)
    return {"status": "success", "source": source}


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    await asyncio.to_thread(delete_source_library, source_id)
    return {"status": "success"}

@app.get("/api/history")
def get_history(session_id: str = "default"):
    loop = get_loop(session_id)
    loop.sync_memory()
    return loop.memory


@app.get("/api/runs")
def list_runs(session_id: str = "", limit: int = 100):
    """List durable run contexts with lightweight GUI replay metadata."""
    runs = []
    for item in list_run_contexts(_ROOT, session_id=session_id, limit=limit):
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
    """Return one durable run context plus its persisted public event replay."""
    sid = safe_session_id(session_id)
    context = load_run_context(_ROOT, sid, run_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Run context not found")
    summary = work_event_run_summary(sid, str(context.get("run_id") or run_id))
    response: Dict[str, Any] = {"status": "success", "run": context, "work_events": summary}
    if include_events:
        events = [
            event
            for event in replay_work_events_after(sid, 0, limit=limit)
            if str(event.get("turn_id") or event.get("run_id") or "") == str(context.get("run_id") or run_id)
        ]
        response["events"] = events
        response["next_sequence"] = max((_safe_event_sequence(event) for event in events), default=0)
    return response


@app.get("/api/work-events")
def get_work_events(request: Request, session_id: str = "default", limit: int = 200, turn_id: str = "", after_sequence: int = 0):
    sid = safe_session_id(session_id)
    replay_work_item_event_log(
        root=_ROOT,
        session_id=sid,
        event_log_path=work_events_path(sid),
    )
    header_cursor = request.headers.get("Last-Event-ID", "").strip()
    if header_cursor:
        try:
            after_sequence = max(after_sequence, int(header_cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer sequence")
    raw_events = _session_work_events(sid)
    retained_sequences = [_safe_event_sequence(event) for event in raw_events if _safe_event_sequence(event) > 0]
    oldest_sequence = min(retained_sequences, default=0)
    replay_truncated = bool(after_sequence and oldest_sequence and after_sequence < oldest_sequence - 1)
    events = (
        replay_work_events_after(sid, after_sequence, limit=limit)
        if after_sequence > 0
        else list_work_events(sid, limit=limit, active_turn_id=turn_id)
    )
    if turn_id:
        events = [event for event in events if str(event.get("turn_id", "")) == turn_id]
    next_sequence = max((_safe_event_sequence(event) for event in events), default=after_sequence)
    return {
        "events": events,
        "after_sequence": after_sequence,
        "next_sequence": next_sequence,
        "oldest_sequence": oldest_sequence,
        "replay_truncated": replay_truncated,
        "projection_failures": pending_work_item_projection_failures(
            event_log_path=work_events_path(sid)
        ),
    }


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
    profile = str(data.get("profile") or "pwsh").strip().lower()
    if profile not in {"pwsh", "cmd", "bash", "wsl"}:
        raise HTTPException(status_code=400, detail="Unsupported terminal profile")
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
    profile = str(data.get("profile") or "pwsh").strip().lower()
    if profile not in {"pwsh", "cmd", "bash", "wsl"}:
        raise HTTPException(status_code=400, detail="Unsupported terminal profile")
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")
    if len(command) > 4000:
        raise HTTPException(status_code=413, detail="Command is too large")

    timeout_raw = data.get("timeout", 90)
    try:
        timeout = max(5, min(int(timeout_raw), 180))
    except Exception:
        timeout = 90

    try:
        from extensions.tools.built_in.nexus_tools.bash_tool import BashTool
    except ModuleNotFoundError:
        from extensions.tools.built_in.bash.scripts.bash import BashTool

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
        "profile": profile,
        "status": "running",
        "turn_id": turn_id,
        "parent_id": parent_event_id,
    }
    if parent_event and parent_event.get("phase"):
        started_payload["phase"] = parent_event.get("phase")
    if parent_event and parent_event.get("phase_index") is not None:
        started_payload["phase_index"] = parent_event.get("phase_index")
    started = append_work_event(sid, started_payload)
    permission = _check_gui_terminal_permission(sid, turn_id, command)
    if not permission.granted:
        blocked = f"Command blocked by permission policy: {permission.reason}"
        completed = append_work_event(sid, {
            **started,
            "id": f"{started.get('id')}_result",
            "status": "error",
            "stdout": "",
            "stderr": blocked,
            "output": blocked,
            "result": blocked,
            "completed_at": time.time(),
        })
        return {"status": "error", "event": completed, "stdout": "", "stderr": blocked, "output": blocked, "command": command}
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
    profile = str(data.get("profile") or "pwsh").strip().lower()
    if profile not in {"pwsh", "cmd", "bash", "wsl"}:
        raise HTTPException(status_code=400, detail="Unsupported terminal profile")
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
            permission = _check_gui_terminal_permission(sid, turn_id, command)
            if not permission.granted:
                blocked = f"Command blocked by permission policy: {permission.reason}"
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

            from sandbox.risk import CommandRiskScorer
            from sandbox.sandbox_manager import SovereignSandbox

            assessment = CommandRiskScorer().assess(command)
            if os.environ.get("NEXUS_ALLOW_DANGEROUS_SHELL", "false").lower() != "true" and assessment and assessment.blocked:
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

            sandbox = SovereignSandbox(_ROOT)
            stream_kwargs = {"timeout": timeout}
            if profile == "pwsh":
                stream_kwargs["shell"] = "powershell"
            elif profile == "cmd":
                stream_kwargs["shell"] = "cmd"
            elif profile == "bash":
                stream_kwargs["shell"] = "bash"
            elif profile == "wsl":
                stream_kwargs["shell"] = "wsl"
            async for text in sandbox.stream_execute(command, _ROOT, **stream_kwargs):
                output_parts.append(text)
                chunks_list.append([time.time() - started_time, text])
                yield sse({"type": "chunk", "stream": "stdout", "text": text})

            return_code = sandbox.last_exit_code if sandbox.last_exit_code is not None else 0
            output = "".join(output_parts)
            status = "done" if return_code == 0 else "error"
            if output.startswith("[SANDBOX_BLOCK]") or "[SANDBOX_TIMEOUT]" in output:
                status = "error"
            stderr = output if status == "error" else ""
            completed = append_work_event(sid, {
                **started,
                "id": f"{started.get('id')}_result",
                "status": status,
                "stdout": output,
                "stderr": stderr,
                "output": output,
                "result": stderr or output,
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


@app.post("/api/run")
def api_run_sync(data: dict, request: Request):
    """Minimal non-stream runner for CLI/tests compatibility."""
    require_config_write_allowed(request)
    command = str(data.get("command") or data.get("target") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    try:
        from sandbox.risk import CommandRiskScorer
        from sandbox.sandbox_manager import SovereignSandbox

        assessment = CommandRiskScorer().assess(command)
        if (
            os.environ.get("NEXUS_ALLOW_DANGEROUS_SHELL", "false").lower() != "true"
            and assessment
            and assessment.blocked
        ):
            raise HTTPException(status_code=403, detail=f"Command blocked by risk policy: {assessment.summary()}")

        # Keep the compatibility endpoint on the same canonical execution
        # path as streamed terminal work. It must never bypass workspace
        # validation by invoking subprocess directly.
        sandbox = SovereignSandbox(_SANDBOX_ROOT)
        output = sandbox.execute(command, _SANDBOX_ROOT)
        return_code = sandbox.last_exit_code if sandbox.last_exit_code is not None else 0
        return {
            "command": command,
            "returncode": return_code,
            "stdout": output,
            "stderr": "",
            "output": output,
        }
    except HTTPException:
        raise
    except Exception as exc:
        return {"command": command, "returncode": 1, "stdout": "", "stderr": str(exc), "output": str(exc)}


@app.get("/api/file-download")
def file_download(path: str):
    file_path = safe_workspace_read_path(path)
    return FileResponse(file_path, filename=os.path.basename(file_path))


@app.post("/api/files/list")
def api_files_list(data: dict):
    target = str(data.get("path", "") or "").strip() or "."
    if not os.path.isabs(target):
        target = os.path.join(_ROOT, target)
    root = os.path.realpath(os.path.abspath(_ROOT))
    target = os.path.realpath(os.path.abspath(target))
    if os.path.commonpath([root, target]) != root:
        raise HTTPException(status_code=400, detail="Path outside workspace")
    if os.path.isfile(target):
        return {
            "path": target,
            "files": [
                {
                    "name": os.path.basename(target),
                    "path": target,
                    "isDirectory": False,
                }
            ],
        }
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Path not found")
    files = []
    for name in os.listdir(target):
        full = os.path.join(target, name)
        files.append({"name": name, "path": full, "isDirectory": os.path.isdir(full)})
    return {"path": target, "files": files}


@app.get("/api/files/tree")
def api_files_tree(path: str = ""):
    """Return one directory level for the GUI folder browser.

    With no path supplied, the agent workspace is the safe, useful default.
    The desktop GUI is local-only, so an operator may also explicitly browse a
    different local folder by supplying its absolute path.
    """
    requested_path = str(path or "").strip()
    target = requested_path or os.path.join(_ROOT, "workspace")
    target = os.path.abspath(os.path.expanduser(os.path.expandvars(target)))

    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Folder not found")

    items = []
    try:
        entries = list(os.scandir(target))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied for this folder")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not open folder: {exc}")

    for entry in sorted(entries, key=lambda value: (not value.is_dir(follow_symlinks=False), value.name.lower())):
        try:
            is_directory = entry.is_dir(follow_symlinks=False)
            items.append({
                "name": entry.name,
                "path": entry.path,
                "type": "directory" if is_directory else "file",
                "size": None if is_directory else entry.stat(follow_symlinks=False).st_size,
            })
        except (OSError, PermissionError):
            # Skip entries that Windows will not let this process inspect.
            continue

    return {"path": target, "items": items}


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
    artifact_root = os.path.realpath(os.path.abspath(_ARTIFACTS_DIR))
    if os.path.isdir(artifact_dir) and os.path.commonpath([artifact_root, os.path.realpath(artifact_dir)]) == artifact_root:
        for name in os.listdir(artifact_dir):
            path = os.path.abspath(os.path.join(artifact_dir, name))
            safe_path = _safe_artifact_file_path(artifact_dir, path)
            if safe_path:
                candidates[f"artifacts/{name}"] = safe_path

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
    return await asyncio.to_thread(
        _create_artifact_sync, data, sid, turn_id, content, lang, name
    )


def _create_artifact_sync(
    data: Dict[str, Any], sid: str, turn_id: str, content: str, lang: str, name: str
):
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
    """Build honest provider status from configure instead of static claims."""
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
    registry_summary = kernel.tools.list_tools(include_unavailable=True)
    for t_name, summary in registry_summary.items():
        if t_name in deleted:
            continue
        tool = kernel.tools.get(t_name)
        cfg_item = custom_cfg.get(t_name) or {}
        if not isinstance(cfg_item, dict):
            cfg_item = {}
        if tool:
            active = cfg_item.get("active", t_name not in disabled)
            available = bool(summary.get("available", tool.is_available())) and bool(active)
            reason = "disabled_by_config" if not active else str(summary.get("availability_reason") or "ready")
            description = cfg_item.get("description") or getattr(tool, "description", "") or tool.schema.get("description", "")
            tools.append(
                {
                    "name": t_name,
                    "description": description,
                    "active": active,
                    "available": available,
                    "availability_reason": reason,
                    "missing_env": summary.get("missing_env", []),
                    "has_handler": bool(summary.get("has_handler", tool.instance is not None)),
                    "config": cfg_item,
                }
            )
    for name, cfg_item in custom_cfg.items():
        if name in deleted:
            continue
        if any(item["name"] == name for item in tools):
            continue
        if isinstance(cfg_item, dict):
            active = cfg_item.get("active", True)
            tools.append(
                {
                    "name": name,
                    "description": cfg_item.get("description", ""),
                    "active": active,
                    "available": False,
                    "availability_reason": "custom_config_only",
                    "missing_env": [],
                    "has_handler": False,
                    "config": cfg_item,
                }
            )
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
    from nexus.runtime.kernel import get_nexus_kernel

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


def _safe_extract_zip(archive: zipfile.ZipFile, destination: str) -> None:
    """Extract an untrusted archive without traversal or symlink escapes."""
    root = os.path.realpath(os.path.abspath(destination))
    os.makedirs(root, exist_ok=True)
    for member in archive.infolist():
        raw_name = str(member.filename or "").replace("\\", "/")
        if not raw_name or raw_name == ".":
            continue
        if raw_name.startswith("/") or re.match(r"^[A-Za-z]:/", raw_name):
            raise RuntimeError("Archive contains an absolute path")
        relative = os.path.normpath(raw_name.replace("/", os.sep))
        if relative in {"", "."}:
            continue
        target = os.path.abspath(os.path.join(root, relative))
        try:
            if os.path.commonpath([root, os.path.realpath(target)]) != root:
                raise RuntimeError("Archive contains a path traversal entry")
        except ValueError:
            raise RuntimeError("Archive contains a path traversal entry") from None
        mode = (int(member.external_attr) >> 16) & 0o170000
        if stat.S_ISLNK(mode):
            raise RuntimeError("Archive contains a symbolic link")
        if member.is_dir() or raw_name.endswith("/"):
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(member, "r") as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)


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
    try:
        with zipfile.ZipFile(temp_zip, "r") as archive:
            _safe_extract_zip(archive, temp_extract)
        entries = [os.path.join(temp_extract, entry) for entry in os.listdir(temp_extract)]
        if not entries:
            raise RuntimeError("Downloaded repository archive was empty")
        shutil.move(entries[0], target_dir)
    finally:
        shutil.rmtree(temp_extract, ignore_errors=True)
        try:
            os.remove(temp_zip)
        except OSError:
            pass


def install_plugin_from_source(raw_url: str, kind: str = "plugin", force: bool = False, enable: bool = True) -> Dict[str, Any]:
    from extensions.plugins.built_in.trust import PluginInstallDisabled, require_unverified_install_opt_in

    try:
        require_unverified_install_opt_in()
    except PluginInstallDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    repo_url, slug = _normalize_repo_url(raw_url)
    kind = str(kind or "plugin").lower()
    install_root = os.path.abspath(os.path.join(_ROOT, "plugins"))
    os.makedirs(install_root, exist_ok=True)
    target = os.path.abspath(os.path.join(install_root, slug))
    if os.path.commonpath([install_root, target]) != install_root:
        raise HTTPException(status_code=400, detail="Invalid plugin target")
    if os.path.lexists(target) and os.path.islink(target):
        raise HTTPException(status_code=409, detail=f"Plugin target '{slug}' is a symbolic link")
    if os.path.exists(target):
        if not force:
            raise HTTPException(status_code=409, detail=f"Plugin '{slug}' already exists. Enable force reinstall to replace it.")
    staging = os.path.join(install_root, f".{slug}.install-{uuid.uuid4().hex}")
    backup = ""
    try:
        subprocess.run(["git", "clone", "--depth", "1", repo_url, staging], cwd=_ROOT, check=True, capture_output=True, text=True, timeout=120)
    except Exception as git_exc:
        try:
            if os.path.lexists(staging):
                shutil.rmtree(staging, ignore_errors=True)
            _download_github_zip(repo_url, staging)
        except Exception as zip_exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Install failed. git: {git_exc}; zip: {zip_exc}")

    try:
        manifest_dir = os.path.join(staging, ".codex-plugin")
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
        if os.path.exists(target):
            if not force:
                raise HTTPException(status_code=409, detail=f"Plugin '{slug}' already exists. Enable force reinstall to replace it.")
            backup = os.path.join(install_root, f".{slug}.backup-{uuid.uuid4().hex}")
            os.replace(target, backup)
        os.replace(staging, target)
    except HTTPException:
        shutil.rmtree(staging, ignore_errors=True)
        if backup and os.path.exists(backup) and not os.path.lexists(target):
            os.replace(backup, target)
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if backup and os.path.exists(backup) and not os.path.lexists(target):
            os.replace(backup, target)
        raise HTTPException(status_code=500, detail=f"Plugin promotion failed: {exc}") from exc
    finally:
        if backup and os.path.exists(backup):
            shutil.rmtree(backup, ignore_errors=True)
    return {"id": f"plugins:{slug}", "path": target, "url": repo_url}


def build_skill_state() -> List[Dict[str, Any]]:
    """Build the dashboard skill list from the on-disk skill registry."""
    try:
        from nexus.runtime.kernel import get_nexus_kernel
        from extensions.skills.built_in import NexusSkillMaster

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
        from evaluation.evidence_ledger import EvidenceLedger
        from observability.mission_replay import MissionReplay
        from maintenance.roadmap import RoadmapAuditor
        from observability.tool_economy import ToolEconomy
        from observability.unified_graph import UnifiedNexusGraph

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
    from evolution.context import EvolutionContextMap

    from maintenance.roadmap import RoadmapAuditor

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
    from evaluation.evidence_ledger import EvidenceLedger
    from maintenance.roadmap import RoadmapAuditor

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
    return {"status": "ok", "service": "nexus-api"}


@app.post("/api/ports/probe")
def probe_local_port(data: dict):
    """Verify that a local TCP service is actually listening before showing it in Ports."""
    raw_port = str(data.get("port", "")).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Enter a valid TCP port number") from exc
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="Port must be between 1 and 65535")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.6)
    try:
        sock.connect(("127.0.0.1", port))
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No local service is listening on port {port}") from exc
    finally:
        sock.close()
    return {"port": port, "address": f"http://127.0.0.1:{port}", "status": "listening"}


@app.post("/api/model")
async def set_model(data: dict, request: Request):
    # The local GUI applies a saved model to its own local session immediately
    # before a chat run. This is a runtime control, not a dashboard-wide config
    # write, so it must work from localhost without a dashboard token.
    require_local_runtime_control(request)
    model = str(data.get("model", "") or "").strip()
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    if model:
        loop.model = model
    return {"status": "success", "sid": sid, "model": loop.model}


@app.get("/api/models/saved")
def get_saved_models():
    """Expose only models that the operator has actually saved in provider config."""
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    providers, _instances = build_provider_state(kernel)
    models = []
    seen = set()
    for provider in providers:
        model = str(provider.get("model") or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        provider_name = str(provider.get("name") or provider.get("id") or "Provider")
        models.append({"model": model, "provider": provider_name, "label": f"{provider_name} · {model}"})
    # provider.yml is the canonical saved-provider file used by this local
    # installation. Include it as well when the runtime config has not yet
    # mirrored profiles into the kernel configuration.
    provider_config = _load_provider_config()
    configured = provider_config.get("providers", {}) if isinstance(provider_config, dict) else {}
    if isinstance(configured, dict):
        for provider_id, profile in configured.items():
            if not isinstance(profile, dict):
                continue
            model = str(profile.get("model") or profile.get("default_model") or "").strip()
            if not model or model in seen:
                continue
            seen.add(model)
            provider_name = str(provider_id).upper()
            models.append({"model": model, "provider": provider_name, "label": f"{provider_name} · {model}"})
    legacy_provider_path = os.path.join(_ROOT, "configure", "provider.yml")
    if os.path.exists(legacy_provider_path):
        try:
            with open(legacy_provider_path, "r", encoding="utf-8") as provider_file:
                legacy_config = yaml.safe_load(provider_file) or {}
            legacy_providers = legacy_config.get("providers", {}) if isinstance(legacy_config, dict) else {}
            if isinstance(legacy_providers, dict):
                for provider_id, profile in legacy_providers.items():
                    if not isinstance(profile, dict):
                        continue
                    model = str(profile.get("model") or profile.get("default_model") or "").strip()
                    if not model or model in seen:
                        continue
                    seen.add(model)
                    provider_name = str(provider_id).upper()
                    models.append({"model": model, "provider": provider_name, "label": f"{provider_name} · {model}"})
        except (OSError, yaml.YAMLError):
            pass
    return {"models": models}


@app.post("/api/mode")
async def set_mode(data: dict, request: Request):
    require_local_runtime_control(request)
    mode = str(data.get("mode", "") or "").strip().lower()
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    loop.permission_mode = mode or loop.permission_mode
    return {"status": "success", "sid": sid, "mode": loop.permission_mode}


@app.get("/api/sandbox")
def get_sandbox():
    """Return the active command execution isolation tier."""
    return {
        "status": "success",
        "tier": _SANDBOX_TIER,
        "root": _SANDBOX_ROOT,
        "available": ["no_sandbox", "normal", "docker"],
        "labels": {
            "no_sandbox": "No Sandbox — full machine access",
            "normal": "Sandbox — Nexus workspace only",
            "docker": "Advanced Sandbox — Docker isolation",
        },
    }


@app.post("/api/sandbox")
async def set_sandbox(data: dict, request: Request):
    """Set command execution to direct, workspace-only, or Docker isolation."""
    require_local_runtime_control(request)
    global _SANDBOX_TIER, _SANDBOX_ROOT
    tier = str(data.get("tier", "") or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"none": "no_sandbox", "off": "no_sandbox", "direct": "no_sandbox", "advanced": "docker"}
    tier = aliases.get(tier, tier)
    if tier not in {"no_sandbox", "normal", "docker"}:
        raise HTTPException(status_code=400, detail="Sandbox must be no_sandbox, normal, or docker.")
    raw_root = str(data.get("root", "") or "").strip()
    selected_root = os.path.abspath(raw_root) if raw_root else os.path.join(_ROOT, "workspace")
    if tier in {"normal", "docker"} and not os.path.isdir(selected_root):
        raise HTTPException(status_code=404, detail=f"Sandbox folder not found: {selected_root}")
    _SANDBOX_TIER = tier
    _SANDBOX_ROOT = selected_root
    os.environ["NEXUS_SANDBOX_TIER"] = tier
    os.environ["NEXUS_SANDBOX_ROOT"] = selected_root
    for loop in _LOOPS.values():
        _apply_sandbox_tier(loop)
    return {"status": "success", "tier": tier, "root": _SANDBOX_ROOT}


@app.post("/api/provider")
async def set_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider = str(data.get("provider", "") or "").strip().lower()
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    loop.provider_override = provider or loop.provider_override
    return {"status": "success", "sid": sid, "provider": loop.provider_override}


@app.post("/api/agent")
async def set_agent(data: dict, request: Request):
    """Store the selected agent identity for the local GUI runtime."""
    require_config_write_allowed(request)
    agent = str(data.get("agent", "") or "").strip()[:200]
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    # The V5 loop does not require a separate agent object to execute, but
    # retaining this selection on the loop keeps settings and future turns
    # consistent across the GUI and the runtime.
    loop.agent = agent
    return {"status": "success", "sid": sid, "agent": agent}


@app.post("/api/goal")
async def set_goal(data: dict, request: Request):
    """Store the active long-running goal for the local GUI runtime."""
    require_config_write_allowed(request)
    goal = str(data.get("goal", "") or "").strip()[:1000]
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    loop.goal = goal
    return {"status": "success", "sid": sid, "goal": goal, "active": bool(goal)}


@app.post("/api/thinking")
async def set_thinking(data: dict, request: Request):
    """Toggle V5 reasoning mode using the loop's public configuration hook."""
    require_config_write_allowed(request)
    enabled = bool(data.get("enabled", True))
    sid = safe_session_id(data.get("session_id", "default") or "default")
    loop = get_loop(sid)
    if hasattr(loop, "configure_thinking"):
        loop.configure_thinking(enabled)
    else:
        loop.thinking_mode = enabled
    return {"status": "success", "sid": sid, "thinking": enabled}


@app.get("/api/state")
def get_state():
    from nexus.runtime.kernel import get_nexus_kernel
    get_nexus_kernel(_ROOT)
    default_provider = refresh_provider_runtime()
    sessions_root = os.path.join(_ROOT, "workspace", "sessions")
    session_titles = {}
    if os.path.isdir(sessions_root):
        for fname in os.listdir(sessions_root):
            if not fname.endswith(".json"):
                continue
            sid = fname[:-5]
            meta_path = os.path.join(sessions_root, f"{sid}.meta")
            title = "Untitled"
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                        title = str(meta.get("title") or title)
                except Exception:
                    pass
            session_titles[sid] = title
    loop = None
    try:
        from nexus.common.session_bus import get_active_session_id
        active_sid = get_active_session_id(_ROOT, "default")
        loop = get_loop(active_sid)
    except Exception:
        loop = None
    provider_name = ""
    model_name = ""
    mode_name = ""
    if loop is not None:
        provider_name = str(getattr(loop, "provider_override", "") or getattr(loop, "provider", "") or default_provider)
        model_name = str(getattr(loop, "model", "") or "")
        mode_name = str(getattr(loop, "permission_mode", "") or getattr(loop, "mode", "") or "")
    return {
        "status": "ok",
        "timestamp": time.time(),
        "root": _ROOT,
        "sessions": session_titles,
        "provider": provider_name,
        "model": model_name,
        "mode": mode_name,
    }


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
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    return kernel.config.data


def _save_kernel_config_sync(kernel: Any, data: Dict[str, Any]) -> None:
    kernel.config.data = data
    if not kernel.config.save():
        raise RuntimeError("Failed to save active profile config")
    if hasattr(kernel.config, "reload"):
        kernel.config.reload()


def _mutate_kernel_config_sync(kernel: Any, mutate) -> None:
    """Apply one config mutation under the kernel lock and persist it."""
    with getattr(kernel, "_lock", threading.RLock()):
        cfg = kernel.config.data
        mutate(cfg)
        _save_kernel_config_sync(kernel, cfg)


@app.post("/api/config")
async def save_config(data: dict, request: Request):
    require_config_write_allowed(request)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Config payload must be an object")
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    try:
        await asyncio.to_thread(_save_kernel_config_sync, kernel, data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _invalidate_dashboard_cache()
    return {"status": "success", "message": "Configuration saved."}


@app.get("/api/plugins")
def list_plugins():
    return {"plugins": discover_plugins()}


@app.get("/api/skills")
def api_skills():
    try:
        from extensions.skills.built_in import NexusSkillMaster
        try:
            NexusSkillMaster(_ROOT)._load_all()
        except Exception:
            pass
    except Exception:
        pass
    return {"skills": build_skill_state()}


@app.get("/api/tools")
def api_tools():
    kernel = None
    try:
        from nexus.runtime.kernel import get_nexus_kernel
        kernel = get_nexus_kernel(_ROOT)
    except Exception:
        pass
    tools = build_tool_state(kernel) if kernel else []
    try:
        from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
        reg = ToolRegistry(_ROOT)
        availability = {name: entry.availability() for name, entry in reg._tools.items()}
    except Exception:
        availability = {}
    for tool in tools:
        status = availability.get(tool.get("name"))
        if isinstance(status, dict):
            if tool.get("active", True) is False:
                tool["available"] = False
                tool["availability_reason"] = "disabled_by_config"
            else:
                tool["available"] = bool(status.get("available"))
                tool["availability_reason"] = status.get("reason") or tool.get("availability_reason") or "unknown"
            tool["missing_env"] = status.get("missing_env", tool.get("missing_env", []))
        else:
            tool["available"] = bool(tool.get("available", tool.get("active", False)))
    return {"tools": tools}


@app.post("/api/tools/{name}/invoke")
async def api_tool_invoke(name: str, data: dict, request: Request):
    require_config_write_allowed(request)
    try:
        from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
        reg = ToolRegistry(_ROOT)
        entry = reg.get(name)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
        if entry.instance is None:
            raise HTTPException(status_code=501, detail=f"Tool '{name}' has no executable handler")
        params = dict(data.get("params", {}))
        params.update({k: v for k, v in data.items() if k != "params"})
        stream = bool(data.get("stream", True))
        if stream:
            async def event_stream():
                try:
                    async for item in reg.stream_execute(name, **params):
                        if isinstance(item, Exception):
                            yield f"data: {json.dumps({'event':'error','error':str(item)}, ensure_ascii=False)}\n\n"
                            return
                        text = "" if item is None else str(item)
                        yield f"data: {json.dumps({'event':'chunk','text':text}, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    yield f"data: {json.dumps({'event':'error','error':str(exc)}, ensure_ascii=False)}\n\n"
            return StreamingResponse(event_stream(), media_type="text/event-stream")
        try:
            result = await reg.execute(name, **params)
            payload = {"success": bool(result.success), "output": result.output, "error": result.error}
        except Exception as exc:
            payload = {"success": False, "output": "", "error": str(exc)}
        return JSONResponse(content=payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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


_LOCAL_PLUGIN_LOCK = threading.RLock()


def _create_local_plugin_sync(
    target: str,
    name: str,
    description: str,
    version: str,
    manifest: Dict[str, Any],
) -> None:
    """Create a local plugin without blocking the async request loop."""
    with _LOCAL_PLUGIN_LOCK:
        if os.path.exists(target):
            raise FileExistsError(target)
        os.makedirs(os.path.join(target, ".codex-plugin"), exist_ok=False)
        os.makedirs(os.path.join(target, "skills"), exist_ok=True)
        os.makedirs(os.path.join(target, "tools"), exist_ok=True)
        try:
            with open(os.path.join(target, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\n{description}\n\nVersion: {version}\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise


def _remove_plugin_tree_sync(path: str) -> None:
    """Remove one already-validated plugin directory off the event loop."""
    with _LOCAL_PLUGIN_LOCK:
        if os.path.lexists(path):
            shutil.rmtree(path)


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
    try:
        await asyncio.to_thread(
            _create_local_plugin_sync,
            target,
            name,
            description,
            version,
            manifest,
        )
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Plugin '{name}' already exists") from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to create plugin on disk") from exc
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

    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    def mutate(cfg):
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

    try:
        await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to save plugin configuration") from exc
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

    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    if plugin.get("disk_removable"):
        path = os.path.abspath(plugin.get("path", ""))
        plugin_root = os.path.abspath(os.path.join(_ROOT, "plugins"))
        resolved_root = os.path.realpath(plugin_root)
        resolved_path = os.path.realpath(path)
        if os.path.commonpath([resolved_root, resolved_path]) != resolved_root:
            raise HTTPException(status_code=400, detail="Plugin path is outside plugins/")
        try:
            await asyncio.to_thread(_remove_plugin_tree_sync, path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Failed to remove plugin from disk") from exc
        message = "Plugin removed from disk."
    else:
        def mutate(cfg):
            deleted = sorted(_config_disabled_set(cfg, "deleted_plugins"))
            if plugin_id not in deleted:
                deleted.append(plugin_id)
            cfg["deleted_plugins"] = deleted

        try:
            await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Failed to save plugin removal") from exc
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

    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    def mutate(cfg):
        key = "custom_skill_configs" if asset_kind == "skills" else "custom_tool_configs"
        cfg.setdefault(key, {})[name] = config
        disabled_key = "disabled_skills" if asset_kind == "skills" else "disabled_tools"
        disabled = sorted(_config_disabled_set(cfg, disabled_key))
        if config.get("active", True) is False:
            if name not in disabled:
                disabled.append(name)
        else:
            disabled = [item for item in disabled if item != name]
        cfg[disabled_key] = disabled
        description_key = "custom_skill_descriptions" if asset_kind == "skills" else "custom_tool_descriptions"
        if config.get("description"):
            cfg.setdefault(description_key, {})[name] = str(config.get("description"))

    try:
        await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save {asset_kind} config") from exc
    _invalidate_dashboard_cache("state", "skills" if asset_kind == "skills" else "tools")
    return {"status": "success", "message": f"{asset_kind[:-1].title()} '{name}' saved."}


async def _delete_asset_config(asset_kind: str, name: str, request: Request):
    require_config_write_allowed(request)
    if asset_kind not in {"skills", "tools"}:
        raise HTTPException(status_code=404, detail="Unknown asset kind")
    item_name = _safe_slug(str(name), "")
    if not item_name:
        raise HTTPException(status_code=400, detail="Asset name is required")
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    def mutate(cfg):
        deleted_key = "deleted_skills" if asset_kind == "skills" else "deleted_tools"
        deleted = sorted(_config_disabled_set(cfg, deleted_key))
        if item_name not in deleted:
            deleted.append(item_name)
        cfg[deleted_key] = deleted
        disabled_key = "disabled_skills" if asset_kind == "skills" else "disabled_tools"
        disabled = sorted(_config_disabled_set(cfg, disabled_key))
        if item_name not in disabled:
            disabled.append(item_name)
        cfg[disabled_key] = disabled
        custom_key = "custom_skill_configs" if asset_kind == "skills" else "custom_tool_configs"
        if isinstance(cfg.get(custom_key), dict):
            cfg[custom_key].pop(item_name, None)

    try:
        await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete {asset_kind[:-1]}") from exc
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
    from nexus.runtime.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    return kernel.hive.list_personas()

@app.post("/api/hive/personas")
async def create_hive_persona(data: dict, request: Request):
    require_config_write_allowed(request)
    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        raise HTTPException(status_code=400, detail="Name and description are required")
    
    from nexus.runtime.kernel import get_nexus_kernel
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
    
    from nexus.runtime.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.modify_persona(name, description)
    if success:
        return {"status": "success", "message": f"Persona '{name}' updated."}
    return {"status": "error", "message": f"Persona '{name}' not found or is reserved."}

@app.delete("/api/hive/personas/{name}")
async def delete_hive_persona(name: str, request: Request):
    require_config_write_allowed(request)
    from nexus.runtime.kernel import get_nexus_kernel
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
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    hive_id = kernel.hive.create_mission(mission, autostart=autostart)
    _invalidate_dashboard_cache("state")
    return {"status": "success", "hive_id": hive_id, "hive": load_hive_state()}


@app.post("/api/hive/{hive_id}/pause")
async def pause_hive(hive_id: str, request: Request):
    require_config_write_allowed(request)
    from nexus.runtime.kernel import get_nexus_kernel

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
    from nexus.runtime.kernel import get_nexus_kernel

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
    from nexus.runtime.kernel import get_nexus_kernel

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
    from nexus.runtime.kernel import get_nexus_kernel

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
    from nexus.runtime.kernel import get_nexus_kernel

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
    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    return kernel.hive.resume_hive(hive_id)


@app.post("/api/mcp/configure")
async def configure_mcp_server(data: dict, request: Request):
    require_config_write_allowed(request)
    name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    config = data.get("config")
    if not name or not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="MCP server name and config object are required")

    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    def mutate(cfg):
        cfg.setdefault("mcp_servers", {})[name] = config

    try:
        await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to persist MCP server configuration") from exc
    return {"status": "success", "name": name}


@app.delete("/api/mcp/delete/{name}")
async def delete_mcp_server(name: str, request: Request):
    require_config_write_allowed(request)
    server_name = re.sub(r"[^a-z0-9_-]", "", str(name).lower())
    if not server_name:
        raise HTTPException(status_code=400, detail="Invalid MCP server name")

    from nexus.runtime.kernel import get_nexus_kernel

    kernel = get_nexus_kernel(_ROOT)
    def mutate(cfg):
        servers = cfg.setdefault("mcp_servers", {})
        servers.pop(server_name, None)

    try:
        await asyncio.to_thread(_mutate_kernel_config_sync, kernel, mutate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to persist MCP server configuration") from exc
    return {"status": "success", "name": server_name}


@app.get("/api/vision/accelerator")
def get_vision_accelerator_state():
    try:
        from extensions.tools.built_in.nexus_tools.vision.vision_accelerator_tool import VisionAccelerator
        return VisionAccelerator().status()
    except ImportError:
        return {"status": "unavailable", "error": "Vision accelerator not installed"}


def _provider_config_path() -> str:
    return os.path.join(_ROOT, "configure", "settings.yml")


def _is_masked_secret_placeholder(value: str) -> bool:
    compact = str(value or "").strip()
    if not compact:
        return False
    mask_chars = {"*", "•", "●", "x", "X"}
    return len(compact) >= 6 and all(char in mask_chars for char in compact)


def _load_provider_config() -> Dict[str, Any]:
    config_path = _provider_config_path()
    if not os.path.exists(config_path):
        return {"providers": {"cloud": {}, "local": {}}}
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=500, detail="Provider configuration is invalid.")
    cfg.setdefault("providers", {}).setdefault("cloud", {})
    cfg.setdefault("providers", {}).setdefault("local", {})
    return cfg


@contextmanager
def _provider_config_transaction():
    """Load/modify/save provider YAML as one cross-process transaction."""
    config_path = _provider_config_path()
    with _PROVIDER_CONFIG_LOCK, _interprocess_event_lock(config_path):
        cfg = _load_provider_config()
        yield cfg


def _save_provider_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_provider_config_path()), exist_ok=True)
    config_path = _provider_config_path()
    temp_path = f"{config_path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, config_path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
    _invalidate_dashboard_cache("state", "providers")


def _add_provider_sync(provider_type_name: str, target_section: str, endpoint: str) -> str:
    with _provider_config_transaction() as cfg:
        section = cfg["providers"].setdefault(target_section, {})
        if provider_type_name not in section:
            section[provider_type_name] = {"active": True, "parent_provider": provider_type_name}
        section[provider_type_name]["active"] = True
        section[provider_type_name]["parent_provider"] = provider_type_name
        if endpoint:
            section[provider_type_name]["endpoint"] = endpoint
        _save_provider_config(cfg)
    return f"Provider '{provider_type_name}' saved."


def _configure_provider_sync(
    provider_type_name: str,
    instance_id: str,
    api_key: str,
    model: str,
    endpoint: str,
) -> str:
    with _provider_config_transaction() as cfg:
        target_section = "local" if provider_type_name in ["ollama", "lm_studio", "llama_cpp"] else "cloud"
        if instance_id not in cfg["providers"][target_section]:
            cfg["providers"][target_section][instance_id] = {"active": True}

        conf = cfg["providers"][target_section][instance_id]
        conf["active"] = True
        conf["parent_provider"] = provider_type_name
        if api_key and not _is_masked_secret_placeholder(api_key):
            conf["api_key"] = api_key
        if model:
            conf["model"] = model
        if endpoint:
            conf["endpoint"] = endpoint
        _save_provider_config(cfg)
    return f"Configuration '{instance_id}' saved."


def _delete_provider_sync(instance_id: str) -> bool:
    with _provider_config_transaction() as cfg:
        deleted = False
        prov_root = cfg.get("providers", {})
        for p_type in ["local", "cloud"]:
            section = prov_root.get(p_type, {})
            if instance_id in section:
                del section[instance_id]
                deleted = True
                break
        if deleted:
            _save_provider_config(cfg)
        return deleted


@app.post("/api/providers/add")
async def add_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider_type_name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    if not provider_type_name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    profile = str(data.get("profile", "cloud")).lower()
    target_section = "local" if profile == "local" or provider_type_name in {"ollama", "lm_studio", "llama_cpp"} else "cloud"
    endpoint = str(data.get("endpoint", "")).strip()
    message = await asyncio.to_thread(
        _add_provider_sync, provider_type_name, target_section, endpoint
    )
    return {"status": "success", "message": message}


@app.post("/api/providers/ping")
async def ping_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    endpoint = str(data.get("endpoint", "")).strip()
    return await asyncio.to_thread(_ping_provider_sync, endpoint)


def _ping_provider_sync(endpoint: str):
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
    
    try:
        message = await asyncio.to_thread(
            _configure_provider_sync,
            provider_type_name,
            instance_id,
            api_key,
            model,
            endpoint,
        )
        return {"status": "success", "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/providers/instance/{instance_id}")
async def delete_provider_instance(instance_id: str, request: Request):
    require_config_write_allowed(request)
    instance_id = re.sub(r"[^a-z0-9_-]", "-", str(instance_id).lower()).strip("-")
    if not instance_id:
        raise HTTPException(status_code=400, detail="Invalid instance id")
    try:
        deleted = await asyncio.to_thread(_delete_provider_sync, instance_id)
        if deleted:
            return {"status": "success", "message": f"Instance {instance_id} deleted."}
        return {"status": "error", "message": f"Instance {instance_id} not found."}
    except Exception as e:
        return {"status": "error", "message": f"Configuration deletion failure: {str(e)}"}

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
            import time

            import psutil
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
    import cv2
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
    import cv2
    import numpy as np
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
    import queue
    import threading

    import cv2

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
    return await asyncio.to_thread(_save_todo_sync, content, session_id, turn_id)


def _save_todo_sync(content: str, session_id: str, turn_id: str):
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
                            
            # Rewrite under the same per-stream lock as append_work_event so a
            # live event cannot be lost between the read and replacement.
            with _WORK_EVENT_LOCK, _interprocess_event_lock(events_file):
                with open(events_file, "w", encoding="utf-8", newline="\n") as f:
                    for evt in non_todo_events:
                        f.write(json.dumps(evt, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                _invalidate_work_event_cache(events_file)
                    
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
