#!/usr/bin/env python3
"""Runtime validation for NEXUS AI CLI v2.1."""
import os, sys, json, time, subprocess, urllib.request, urllib.error, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = 0; FAIL = 0; ERRORS = []

def report(label, ok, detail=""):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  ✅ {label}")
    else: FAIL += 1; ERRORS.append(f"{label}: {detail}"); print(f"  ❌ {label}: {detail}")

print("═" * 60)
print(" NEXUS AI v2.1 — Runtime Validation")
print("═" * 60)

# ── 1. Boot Tests ─────────────────────────────────────────────────────────────
print("\n1. Boot")
try:
    import nexus
    report("nexus.py imports", True)
except Exception as e:
    report("nexus.py imports", False, str(e))

# ── 2. Shell Tests ─────────────────────────────────────────────────────────────
print("\n2. Shell")
try:
    from shell import TaskTracker, NexusShell, _load_history, _save_history
    tid = TaskTracker.create("Runtime test")
    TaskTracker.update(tid, "completed")
    tasks = TaskTracker.list()
    report("TaskTracker", len(tasks) > 0, f"{len(tasks)} tasks")
except Exception as e:
    report("TaskTracker", False, str(e))

# ── 3. Server + API ──────────────────────────────────────────────────────────
print("\n3. Server + API")
import uvicorn
import asyncio
from server import app, _ROOT, _SESSION_DIR, safe_session_id

# Start server in thread
def run_server():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="warning")
        srv = uvicorn.Server(config)
        loop.run_until_complete(srv.serve())
    except Exception as e:
        print(f"Server thread error: {e}")

srv_thread = threading.Thread(target=run_server, daemon=True)
srv_thread.start()
time.sleep(2)
report("Server thread", srv_thread.is_alive())

API = "http://127.0.0.1:8001/api"

def api_get(path):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

def api_post(path, data, method="POST"):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"{API}{path}", data=body,
            headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

# Health
d = api_get("/health")
report("GET /health", d.get("status") == "ok", str(d)[:60])

# Skills
d = api_get("/skills")
report("GET /skills", "skills" in d, str(d.get("_error", ""))[:60])

# Tools
d = api_get("/tools")
report("GET /tools", "tools" in d, str(d.get("_error", ""))[:60])

# Agents
d = api_get("/agents")
report("GET /agents", "agents" in d, str(d.get("_error", ""))[:60])

# Plugins
d = api_get("/plugins")
report("GET /plugins", "plugins" in d, str(d.get("_error", ""))[:60])

# Status
d = api_get("/status")
report("GET /status", d.get("version") == "2.1.0", str(d.get("_error", ""))[:60])

# Sessions
d = api_get("/sessions")
report("GET /sessions", isinstance(d, list), str(d)[:60])

# Create session
d = api_post("/sessions/new", {})
report("POST /sessions/new", "id" in d, str(d.get("_error", ""))[:60])

# Mode
d = api_post("/mode", {"mode": "plan"})
report("POST /mode", d.get("status") == "success", str(d.get("_error", ""))[:60])

# Model
d = api_post("/model", {"model": "kimi-k2.6"})
report("POST /model", d.get("status") == "success", str(d.get("_error", ""))[:60])

# Agent
d = api_post("/agent", {"agent": "nexus-coder"})
report("POST /agent", d.get("status") == "success", str(d.get("_error", ""))[:60])

# Files search
d = api_get("/files?q=py")
report("GET /files", "files" in d and len(d["files"]) >= 0, str(d.get("_error", ""))[:60])

# Run safe
d = api_post("/run", {"command": "echo hello-v2.1"})
report("POST /run (safe)", "hello-v2.1" in str(d.get("output", "")), f"returncode={d.get('returncode')}")

# Run blocked
d = api_post("/run", {"command": "rm -rf /"})
report("POST /run (blocked)", d.get("returncode") == -1 or "Forbidden" in str(d), f"returncode={d.get('returncode')}")

# Task lifecycle
d = api_post("/tasks", {"subject": "E2E task", "agent": "test"})
report("POST /tasks", "task" in d, str(d.get("_error", ""))[:60])
tid = d.get("task", {}).get("id", "") if "task" in d else ""
if tid:
    d2 = api_post(f"/tasks/{tid}", {"status": "in_progress"}, method="PATCH")
    report("PATCH /tasks/{id}", d2.get("status") == "updated", str(d2.get("_error", ""))[:60])

# Multi-agent
d = api_post("/multi_agent", {"command": "/review", "prompt": "test"})
report("POST /multi_agent", d.get("status") == "started", str(d.get("_error", ""))[:60])

# Chat stream
try:
    body = json.dumps({"prompt": "say hello v2.1", "session_id": "runtime_test"}).encode()
    req = urllib.request.Request(f"{API}/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read().decode()
        has_it = "data:" in data and ("hello" in data.lower() or "NEXUS" in data or len(data) > 50)
        report("POST /chat stream", has_it, f"Got {len(data)} chars")
except Exception as e:
    report("POST /chat stream", False, str(e)[:60])

# ── 4. Summary ────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print(f" RESULT: {PASS} passed | {FAIL} failed")
print("═" * 60)

if ERRORS:
    print("\nFailures:")
    for e in ERRORS:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("\n🎉 ALL RUNTIME TESTS PASSED")
    sys.exit(0)
