import os
import json
import yaml
import re
import shutil
import time
import threading
import concurrent.futures
from typing import List, Dict, Any
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from orchestrators.loop import NexusLoop

# 🌌 [NEXUS_PATH_CORE]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOAD_DIR = os.path.join(_ROOT, "workspace", "uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)
_API_AUDIT_LOG = os.path.join(_ROOT, "logs", "dashboard_api.jsonl")
_LOCAL_ONLY = os.environ.get("NEXUS_DASHBOARD_LOCAL_ONLY", "true").lower() == "true"
_AUTH_TOKEN = os.environ.get("NEXUS_DASHBOARD_TOKEN", "").strip()
_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT = int(os.environ.get("NEXUS_DASHBOARD_RATE_LIMIT", "240"))
_RATE_BUCKETS: Dict[str, List[float]] = {}
_MAX_UPLOAD_BYTES = int(os.environ.get("NEXUS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
_ALLOWED_UPLOAD_EXTS = {".txt", ".md", ".json", ".py", ".js", ".ts", ".tsx", ".css", ".yaml", ".yml", ".csv", ".log"}
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}

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
    if _AUTH_TOKEN:
        supplied = request.headers.get("x-nexus-token", "")
        if supplied != _AUTH_TOKEN:
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

def get_loop(session_id: str = "default") -> NexusLoop:
    session_id = safe_session_id(session_id)
    if session_id not in _LOOPS:
        loop = NexusLoop(root_dir=_ROOT)
        loop.load_memory(session_id)
        _LOOPS[session_id] = loop
    return _LOOPS[session_id]

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
    new_id = f"session_{int(time.time())}"
    loop = get_loop(new_id)
    loop.save_memory()
    return {"id": new_id, "title": "New Chat"}

@app.post("/api/sessions/load")
async def load_session(request: Request):
    data = await request.json()
    sid = safe_session_id(data.get("id", "default"))
    loop = get_loop(sid)
    return {"status": "success", "id": loop.session_id, "history": loop.memory}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, request: Request):
    require_config_write_allowed(request)
    session_id = safe_session_id(session_id)
    if session_id == "default":
        raise HTTPException(status_code=400, detail="Default session cannot be deleted")
    path = session_file_path(session_id)
    if os.path.exists(path):
        os.remove(path)
        if session_id in _LOOPS:
            del _LOOPS[session_id]
        return {"status": "success", "id": session_id, "deleted": True}
    return {"status": "error", "id": session_id, "deleted": False, "message": "Session not found"}

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
    data = await request.json()
    prompt = str(data.get("prompt", ""))[:50000]
    sid = safe_session_id(data.get("session_id", "default"))
    loop = get_loop(sid)
    
    # Normalize provider
    from core.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    default_p = kernel.config.get_system("provider_name", "openrouter")
    raw_provider = data.get("provider") or default_p
    provider = str(raw_provider).lower().replace(" ", "_")
    
    async def event_generator():
        try:
            for chunk in loop.stream_run(prompt, provider=provider):
                if chunk:
                    yield chunk
        except Exception as e:
            print(f"[CHAT_ERROR]: {e}")
            yield f"\n[NEXUS_SYSTEM_ERROR]: {str(e)}"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    saved_paths = []
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
    
    # Notify brain_loop about new files if needed
    # brain_loop.inject_system_message(f"[SYSTEM]: User uploaded {len(saved_paths)} files to workspace/uploads.")
    
    return {"status": "success", "files": saved_paths}

@app.get("/api/history")
def get_history(session_id: str = "default"):
    loop = get_loop(session_id)
    loop.sync_memory()
    return loop.memory

# 🛡️ [STATE_CACHE]
_CACHE = {"state": None, "last_update": 0, "audit": None, "audit_last_update": 0}
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


def load_hive_state(limit: int = 10) -> List[Dict[str, Any]]:
    """Return recent real hive progress from the persisted manifest."""
    manifest = os.path.join(_ROOT, "logs", "hive", "hive_manifest.json")
    if not os.path.exists(manifest):
        return []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[API_ERROR]: Failed to load hive manifest: {e}")
        return []

    hives: Dict[str, Dict[str, Any]] = {}
    for task in data.get("tasks", []):
        hive_id = task.get("hive_id") or "unknown"
        item = hives.setdefault(
            hive_id,
            {
                "id": hive_id,
                "total": 0,
                "by_status": {},
                "roles": [],
                "updated_at": 0,
            },
        )
        status = task.get("status", "unknown")
        role = task.get("role", "WORKER")
        item["total"] += 1
        item["by_status"][status] = item["by_status"].get(status, 0) + 1
        if role not in item["roles"]:
            item["roles"].append(role)
        item["updated_at"] = max(item["updated_at"], float(task.get("updated_at", 0) or 0))

    return sorted(hives.values(), key=lambda x: x["updated_at"], reverse=True)[:limit]


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
            item = {
                "id": provider_id,
                "name": provider_id.upper(),
                "status": status,
                "profile": section_name,
                "parent": str(parent).upper(),
                "model": model,
                "description": f"{section_name.title()} provider profile for {parent}.",
            }
            providers.append(item)
            if active:
                instances.append(
                    {
                        "id": provider_id,
                        "parent": str(parent).upper(),
                        "model": model,
                        "profile": section_name,
                        "status": status,
                    }
                )
    providers.sort(key=lambda p: (p["status"] != "ACTIVE", p["profile"], p["id"]))
    return providers, instances


def build_audit_state() -> Dict[str, Any]:
    """Return compact control-plane status. Never raises — returns empty on error."""
    try:
        from core.aurora.evidence_ledger import EvidenceLedger
        from core.aurora.mission_replay import MissionReplay
        from core.aurora.roadmap import RoadmapAuditor
        from core.aurora.tool_economy import ToolEconomy
        from core.aurora.unified_graph import UnifiedNexusGraph

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


@app.get("/api/state")
def get_state():
    now = time.time()
    if _CACHE["state"] and (now - _CACHE["last_update"]) < 2.0:
        return _CACHE["state"]

    try:
        from core.kernel import get_nexus_kernel
        kernel = get_nexus_kernel(_ROOT)

        tools = []
        for t_name in kernel.tools.list_tools():
            tool = kernel.tools.get(t_name)
            if tool:
                tools.append({"name": t_name, "description": tool.description})

        providers_list, provider_instances = build_provider_state(kernel)
        stats = kernel.get_stats()
        health = {"cpu": stats["load"]["cpu"], "ram": stats["load"]["ram"], "status": stats["status"]}
    except Exception as exc:
        print(f"[API_WARN] kernel init failed: {exc}")
        tools = []
        providers_list, provider_instances = [], []
        health = {"cpu": "0%", "ram": "0%", "status": "DEGRADED"}

    result = {
        "hive": load_hive_state(),
        "skills": tools,
        "tools": tools,
        "providers": providers_list,
        "provider_instances": provider_instances,
        "mcp": {"connected": 0, "total": 1, "servers": []},
        "health": health,
        "session": {"active": True, "turns": 0},
        "reminders": [],
        "audit": get_async_audit_state(),
    }

    _CACHE["state"] = result
    _CACHE["last_update"] = now
    return result


@app.get("/api/audit")
def get_audit_state():
    return build_audit_state()

# ── Hive Persona Management ──────────────────────────────────────────────────

@app.get("/api/hive/personas")
def list_hive_personas():
    from core.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    return kernel.hive.list_personas()

@app.post("/api/hive/personas")
async def create_hive_persona(data: dict, request: Request):
    require_config_write_allowed(request)
    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        raise HTTPException(status_code=400, detail="Name and description are required")
    
    from core.kernel import get_nexus_kernel
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
    
    from core.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.modify_persona(name, description)
    if success:
        return {"status": "success", "message": f"Persona '{name}' updated."}
    return {"status": "error", "message": f"Persona '{name}' not found or is reserved."}

@app.delete("/api/hive/personas/{name}")
async def delete_hive_persona(name: str, request: Request):
    require_config_write_allowed(request)
    from core.kernel import get_nexus_kernel
    kernel = get_nexus_kernel(_ROOT)
    success = kernel.hive.delete_persona(name)
    if success:
        return {"status": "success", "message": f"Persona '{name}' deleted."}
    return {"status": "error", "message": f"Persona '{name}' not found or is reserved."}


@app.get("/api/vision/accelerator")
def get_vision_accelerator_state():
    from tools.nexus_tools.vision.vision_accelerator import VisionAccelerator

    return VisionAccelerator().status()


@app.post("/api/providers/configure")
async def configure_provider(data: dict, request: Request):
    require_config_write_allowed(request)
    provider_type_name = re.sub(r"[^a-z0-9_-]", "", str(data.get("name", "")).lower())
    instance_id = re.sub(r"[^a-z0-9_-]", "-", str(data.get("instance_id", provider_type_name)).lower()).strip("-")
    api_key = str(data.get("api_key", "")).strip()
    model = str(data.get("model", "")).strip()
    if not provider_type_name or not instance_id:
        raise HTTPException(status_code=400, detail="Provider name and instance id are required")
    
    config_path = os.path.join(_ROOT, "configs", "nexus_config.yaml")
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
            
            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)
            
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
    config_path = os.path.join(_ROOT, "configs", "nexus_config.yaml")
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
                with open(config_path, "w") as f:
                    yaml.dump(cfg, f, default_flow_style=False)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
