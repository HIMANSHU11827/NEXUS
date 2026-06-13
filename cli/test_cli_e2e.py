"""End-to-end test for NEXUS AI CLI v2.1 backend."""
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = 0
FAIL = 0
ERRORS = []

def report(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        ERRORS.append(f"{label}: {detail}")
        print(f"  ❌ {label}: {detail}")

print("═" * 60)
print(" NEXUS AI CLI v2.1 — End-to-End Test")
print("═" * 60)

# ── 1. Import Tests ──────────────────────────────────────────────────────────
print("\n1. Imports")
try:
    import server
    report("server.py import", True)
except Exception as e:
    report("server.py import", False, str(e))

try:
    import shell
    report("shell.py import", True)
except Exception as e:
    report("shell.py import", False, str(e))

try:
    import nexus
    report("nexus.py import", True)
except Exception as e:
    report("nexus.py import", False, str(e))

# ── 2. Server Startup ────────────────────────────────────────────────────────
print("\n2. Server Startup")
import threading
import uvicorn
from server import app

server_thread = None
_server_ready = False

def run_server():
    global _server_ready
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
        srv = uvicorn.Server(config)
        _server_ready = True
        loop.run_until_complete(srv.serve())
    except Exception as e:
        _server_ready = True
        print(f"Server error: {e}")

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(2)
report("Server thread started", server_thread.is_alive())

# Wait for server to be ready
for _ in range(30):
    time.sleep(0.5)
    if _server_ready:
        break

# ── 3. API Health ────────────────────────────────────────────────────────────
print("\n3. API Endpoints")
import urllib.request
import urllib.error
import json

API = "http://127.0.0.1:8000/api"

def api_get(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

def api_post(path: str, data: dict, method: str = "POST") -> dict:
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{API}{path}", data=body,
            headers={"Content-Type": "application/json"}, method=method
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

# Health
health = api_get("/health")
report("GET /api/health", health.get("status") == "ok", str(health)[:80])

# Skills
skills = api_get("/skills")
report("GET /api/skills", "skills" in skills, str(skills.get("_error", ""))[:80])

# Tools
tools = api_get("/tools")
report("GET /api/tools", "tools" in tools, str(tools.get("_error", ""))[:80])

# Agents
agents = api_get("/agents")
report("GET /api/agents", "agents" in agents, str(agents.get("_error", ""))[:80])

# Plugins
plugins = api_get("/plugins")
report("GET /api/plugins", "plugins" in plugins, str(plugins.get("_error", ""))[:80])

# Status
status = api_get("/status")
report("GET /api/status", status.get("health") == "ok", str(status.get("_error", ""))[:80])

# Sessions
sessions = api_get("/sessions")
report("GET /api/sessions", isinstance(sessions, list), str(sessions)[:80])

# Create session
new_session = api_post("/sessions/new", {})
report("POST /api/sessions/new", "id" in new_session, str(new_session.get("_error", ""))[:80])

# Mode
mode_res = api_post("/mode", {"mode": "plan"})
report("POST /api/mode", mode_res.get("status") == "success", str(mode_res.get("_error", ""))[:80])

# Model
model_res = api_post("/model", {"model": "kimi-k2.6"})
report("POST /api/model", model_res.get("status") == "success", str(model_res.get("_error", ""))[:80])

# Agent
agent_res = api_post("/agent", {"agent": "nexus-coder"})
report("POST /api/agent", agent_res.get("status") == "success", str(agent_res.get("_error", ""))[:80])

# Task create
task_res = api_post("/tasks", {"subject": "Test task", "agent": "test"})
report("POST /api/tasks", "task" in task_res, str(task_res.get("_error", ""))[:80])

# Task patch
tid = task_res.get("task", {}).get("id", "") if "task" in task_res else ""
if tid:
    patch_res = api_post(f"/tasks/{tid}", {"status": "in_progress"}, method="PATCH")
    report("PATCH /api/tasks/{id}", patch_res.get("status") == "updated", str(patch_res.get("_error", ""))[:80])

# Run (safe)
run_res = api_post("/run", {"command": "echo hello"})
report("POST /api/run", run_res.get("returncode") == 0, str(run_res.get("_error", ""))[:80])

# Run (dangerous blocked)
run_danger = api_post("/run", {"command": "rm -rf /"})
blocked = run_danger.get("returncode") == -1 or "BLOCKED" in str(run_danger) or "Forbidden" in str(run_danger) or run_danger.get("_error", "").startswith("HTTP Error 403")
report("POST /api/run (dangerous)", blocked, str(run_danger.get("_error", run_danger))[:80])

# Multi-agent
ma_res = api_post("/multi_agent", {"command": "/review", "prompt": "test"})
report("POST /api/multi_agent", ma_res.get("status") == "started", str(ma_res.get("_error", ""))[:80])

# ── 4. Chat Stream ───────────────────────────────────────────────────────────
print("\n4. Chat Stream")
try:
    body = json.dumps({"prompt": "say hello", "session_id": "test_e2e"}).encode()
    req = urllib.request.Request(
        f"{API}/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read().decode()
        has_data = "data:" in data or "Hello" in data or "NEXUS" in data
        report("POST /api/chat stream", has_data, f"Got {len(data)} chars")
except Exception as e:
    report("POST /api/chat stream", False, str(e)[:80])

# ── 5. Shell Class Test ──────────────────────────────────────────────────────
print("\n5. Shell Class")
try:
    from shell import TaskTracker, NexusShell
    tid = TaskTracker.create("E2E test", agent="test")
    TaskTracker.update(tid, "completed")
    tasks = TaskTracker.list()
    report("TaskTracker", any(t["id"] == tid for t in tasks), f"{len(tasks)} tasks")
except Exception as e:
    report("TaskTracker", False, str(e)[:80])

# ── 6. Summary ───────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print(f" RESULT: {PASS} passed | {FAIL} failed")
print("═" * 60)

if ERRORS:
    print("\nFailures:")
    for e in ERRORS:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("\n🎉 ALL TESTS PASSED")
    sys.exit(0)
