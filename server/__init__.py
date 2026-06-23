"""
Standalone HTTP API server for NEXUS AI.
Designed for the Ink CLI and external clients.
No vision models, no dashboard bloat — just the chat API.
"""

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from orchestrators.loop import NexusLoop

try:
    import yaml
except Exception:  # pragma: no cover - handled at request time
    yaml = None

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ROOT)  # One level up from server/ to project root
_LOOPS: Dict[str, NexusLoop] = {}
_MAX_LOOPS = 20  # Prevent unbounded memory growth
_SESSION_DIR = os.path.join(_ROOT, "logs", "sessions")
_TASKS_PATH = os.path.join(_ROOT, "logs", "tasks.json")
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "nexus_config.yaml")
_CLAUDE_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, ".claude", "settings.json")
_RUNTIME_SETTINGS = {
    "model": "",
    "provider": "",
    "mode": "auto",
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

app = FastAPI(title="NEXUS AI API", version="2.1.0")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}" if str(exc) else "Internal server error"}
    )

# Allow CORS for local GUI
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _trim_loops():
    """Evict oldest loop sessions if over limit."""
    if len(_LOOPS) > _MAX_LOOPS:
        # Evict oldest (arbitrary order since dict preserves insertion)
        keys = list(_LOOPS.keys())
        for k in keys[:len(keys) - _MAX_LOOPS]:
            try:
                del _LOOPS[k]
            except KeyError:
                pass


def safe_session_id(session_id: str) -> str:
    raw = os.path.basename(str(session_id or "default")).replace(".json", "")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return cleaned or "default"


def session_file_path(session_id: str, suffix: str = ".json") -> str:
    os.makedirs(_SESSION_DIR, exist_ok=True)
    safe_id = safe_session_id(session_id)
    path = os.path.abspath(os.path.join(_SESSION_DIR, f"{safe_id}{suffix}"))
    root = os.path.abspath(_SESSION_DIR)
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return path


def get_loop(session_id: str = "default") -> NexusLoop:
    sid = safe_session_id(session_id)
    if sid not in _LOOPS:
        loop = NexusLoop(root_dir=_PROJECT_ROOT)
        try:
            loop.load_memory(sid)
        except Exception:
            pass
        apply_runtime_settings(loop)
        _LOOPS[sid] = loop
        _trim_loops()
    return _LOOPS[sid]


def set_active_session(session_id: str, source: str = "cli-api") -> None:
    try:
        from session_bus import set_active_session_id
        set_active_session_id(_PROJECT_ROOT, session_id, source=source)
    except Exception:
        pass


def apply_runtime_settings(loop: NexusLoop) -> None:
    """Apply CLI-selected runtime settings to a loop instance."""
    model = str(_RUNTIME_SETTINGS.get("model") or "").strip()
    provider = str(_RUNTIME_SETTINGS.get("provider") or "").strip()
    mode = str(_RUNTIME_SETTINGS.get("mode") or "auto").strip().lower()
    agent = str(_RUNTIME_SETTINGS.get("agent") or "").strip()
    goal = str(_RUNTIME_SETTINGS.get("goal") or "").strip()
    additional_dirs = _RUNTIME_SETTINGS.get("additional_dirs") or []

    loop.model = model
    loop.provider_override = provider
    loop.permission_mode = mode
    loop.active_agent = agent
    loop.active_goal = goal
    loop.additional_dirs = [str(item) for item in additional_dirs if str(item).strip()]

    if provider:
        try:
            loop.brain.set_override(provider)
        except Exception:
            pass

    if model:
        try:
            active_provider = getattr(loop.brain.base_router, "provider", None)
            if active_provider is not None and hasattr(active_provider, "model"):
                active_provider.model = model
        except Exception:
            pass

    try:
        from permissions import PermissionMode
        mode_map = {
            "auto": PermissionMode.AUTO,
            "plan": PermissionMode.PLAN,
            "acceptedits": PermissionMode.AUTO_PILOT,
            "accept": PermissionMode.AUTO_PILOT,
            "dontask": PermissionMode.BYPASS,
            "bypass": PermissionMode.BYPASS,
            "approve": PermissionMode.APPROVE,
            "default": PermissionMode.DEFAULT,
        }
        loop.permissions.set_mode(mode_map.get(mode, PermissionMode.AUTO))
    except Exception:
        pass


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
        except Exception:
            pass
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
            except Exception:
                pass

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
        return {"status": "success", "id": loop.session_id, "history": loop.memory}
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

@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    prompt = str(data.get("prompt", "")).strip()[:50000]
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required and cannot be empty")

    sid = safe_session_id(data.get("session_id", "default"))
    provider = str(data.get("provider", "")).lower().replace(" ", "_")
    model = str(data.get("model", "")).strip()
    stream = bool(data.get("stream", False))

    try:
        nexus_loop = get_loop(sid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize session: {str(e)}")

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
        try:
            async for chunk in nexus_loop.stream_run(prompt, provider=safe_provider, model=safe_model):
                if chunk.get("type") == "content":
                    yield f"data: {chunk['data']}\n\n"
        except asyncio.TimeoutError:
            yield "event: error\ndata: [NEXUS_SYSTEM_ERROR]: Response timed out after 30 seconds\n\n"
        except GeneratorExit:
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            safe_err = str(e).replace('\n', ' ').replace('\r', '')
            yield f"event: error\ndata: [NEXUS_SYSTEM_ERROR]: {safe_err}\n\n"

    if stream:
        return StreamingResponse(async_generator(), media_type="text/event-stream")
    else:
        gen = nexus_loop.stream_run(prompt, provider=safe_provider, model=safe_model)
        text = await _collect_all(gen)
        return {"response": text}


@app.get("/api/history")
def get_history(session_id: str = "default"):
    try:
        loop = get_loop(session_id)
        loop.sync_memory()
        return loop.memory
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get history: {str(e)}")


# ── New CLI Backend Endpoints ────────────────────────────────────────────────

_TASKS: Dict[str, dict] = _load_tasks()
_TASK_COUNTER = max([int(k.split("_")[1]) for k in _TASKS if "_" in k] or [0])


@app.get("/api/skills")
def list_skills():
    """List available skills from project config and .commandcode/skills."""
    summary = _config_summary()
    by_name = {skill["name"]: skill for skill in summary["skills"]}
    skills_dir = os.path.join(_PROJECT_ROOT, ".commandcode", "skills")
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, name, "SKILL.md")
            desc = ""
            if os.path.exists(skill_path):
                try:
                    with open(skill_path, "r", encoding="utf-8") as f:
                        desc = f.readline().strip().lstrip("# ")[:80]
                except Exception:
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
        registry = ToolRegistry()
        tools = []
        for name in sorted(registry.list_tools()):
            tool = registry.get(name)
            if tool:
                cfg = config_tools.get(name, {})
                tools.append({
                    "name": name,
                    "description": cfg.get("description") or getattr(tool, "description", "")[:80],
                    "read_only": getattr(tool, "is_read_only", lambda: False)(),
                    "safe": getattr(tool, "is_concurrency_safe", lambda: False)(),
                    "enabled": bool(cfg.get("enabled", True))
                })
        seen = {tool["name"] for tool in tools}
        for name, cfg in config_tools.items():
            if name not in seen:
                tools.append({
                    "name": name,
                    "description": cfg.get("description", ""),
                    "read_only": False,
                    "safe": False,
                    "enabled": bool(cfg.get("enabled", True))
                })
        return {"tools": tools}
    except Exception as e:
        return {"tools": list(config_tools.values()), "error": str(e)}


@app.get("/api/agents")
def list_agents():
    """List available agents from .commandcode/agents and hive personas."""
    agents = []
    seen = set()

    agents_dir = os.path.join(_PROJECT_ROOT, ".commandcode", "agents")
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
        pass

    try:
        from config_loader import get_config
        pm = get_config()
        for profile in pm.list_profiles():
            key = profile.lower()
            if key not in seen:
                agents.append({
                    "id": profile,
                    "name": profile.replace("-", " ").title(),
                    "status": "idle",
                    "description": f"NEXUS profile: {profile}"
                })
                seen.add(key)
    except Exception:
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
            from config_loader import get_config
            pm = get_config()
            for p in pm.get_active_providers():
                active_providers_from_kernel.add(p.lower())
        except Exception:
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
                pass
            _clear_runtime("tools reloaded")

        elif target_type in {"skill", "skills"}:
            try:
                from skills import NexusSkillMaster
                NexusSkillMaster._reset_instance()
            except Exception:
                pass
            _clear_runtime("skills reloaded")

        elif target_type in {"mcp", "mcps", "mcp_server"}:
            _clear_runtime("mcp config reloaded")

        elif target_type in {"provider", "providers"}:
            try:
                from providers.factory import NexusProviderFactory
                NexusProviderFactory._reset_instance()
            except Exception:
                pass
            _clear_runtime("providers reloaded")

        elif target_type == "config":
            try:
                from config_loader import get_config
                get_config().reload()
            except Exception:
                pass

        return {"status": "success", "target": target_type, "summary": _config_summary()}

    if action == "reset":
        if target_type in {"nexus", "runtime", "loops", "all", ""}:
            _RUNTIME_SETTINGS.update({"model": "", "provider": "", "mode": "auto", "agent": "", "goal": "", "additional_dirs": []})
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
    return {"tasks": list(_TASKS.values())}


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
        "mode": _RUNTIME_SETTINGS.get("mode") or "auto",
        "provider": _RUNTIME_SETTINGS.get("provider") or getattr(active_provider, "provider_name", "") or "auto",
        "agent": _RUNTIME_SETTINGS.get("agent") or "",
        "goal": _RUNTIME_SETTINGS.get("goal") or "",
        "sandbox_tier": _RUNTIME_SETTINGS.get("sandbox_tier", "no_sandbox"),
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
    mode = str(data.get("mode", "auto")).lower()
    allowed = {"auto", "plan", "acceptedits", "accept", "dontask", "bypass", "approve", "default"}
    if mode not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Choose from: {', '.join(allowed)}")
    _RUNTIME_SETTINGS["mode"] = mode
    apply_runtime_to_all_loops()
    return {"status": "success", "mode": mode}


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
        "tier": _RUNTIME_SETTINGS.get("sandbox_tier", "no_sandbox"),
        "available": ["no_sandbox", "normal", "docker"],
    }


@app.post("/api/sandbox")
async def set_sandbox(request: Request):
    """Set the sandbox tier: no_sandbox, normal, or docker."""
    data = await request.json()
    tier = str(data.get("tier", "")).strip().lower()
    valid = {"no_sandbox", "normal", "docker"}
    if tier not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid sandbox tier. Choose from: {', '.join(sorted(valid))}")
    _RUNTIME_SETTINGS["sandbox_tier"] = tier
    os.environ["NEXUS_SANDBOX_TIER"] = tier
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
async def run_command(request: Request):
    """Run a bash command (read-only or safe only)."""
    data = await request.json()
    command = str(data.get("command", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="No command provided")

    # Reject dangerous commands
    dangerous = {"rm -rf", "sudo", "mkfs", "dd if=", "> /dev", ":(){"}
    lowered = command.lower()
    for d in dangerous:
        if d in lowered:
            raise HTTPException(status_code=403, detail=f"Dangerous command blocked: {d}")

    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
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
        for dirpath, _, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            # Skip common noise dirs
            if any(part.startswith((".", "node_modules", "__pycache__", "venv", ".venv")) for part in rel.split(os.sep)):
                continue
            for fname in filenames:
                full = os.path.join(rel, fname)
                if q_lower in full.lower() and len(files) < 10:
                    files.append(full)
                if len(files) >= 10:
                    break
            if len(files) >= 10:
                break
    except Exception:
        pass
    return {"files": files[:10]}


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
    from utils.engine_manager import get_engine_status, load_or_create_config
    try:
        return {
            "status": get_engine_status(),
            "config": load_or_create_config()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/engine/config")
async def update_engine_config(request: Request):
    from utils.engine_manager import load_or_create_config, save_config
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
    from utils.engine_compiler import compile_llama_cpp
    try:
        res = compile_llama_cpp()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/engine/reload")
async def reload_local_engine(request: Request):
    from utils.engine_manager import reload_engine
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
    import sys
    import platform
    import subprocess
    
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
    
    status_file = os.path.join(_PROJECT_ROOT, "configs", "self_improvement_status.json")
    status = {"status": "idle", "message": "No training has been run yet."}
    
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                status = json.load(f)
        except Exception:
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

