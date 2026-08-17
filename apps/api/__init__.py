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
import sys
import shutil
import socket
import sqlite3
import threading
import tempfile
import time
import uuid
import urllib.parse
from contextlib import asynccontextmanager, contextmanager
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

_ENV_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Support both project-local env locations while preserving explicit process
# settings supplied by a launcher or deployment environment.
load_dotenv(os.path.join(_ENV_PROJECT_ROOT, ".env"), override=False)
load_dotenv(os.path.join(_ENV_PROJECT_ROOT, "configure", ".env"), override=False)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from nexus.events import CanonicalEvent
from nexus.run_context import list_run_contexts, load_run_context
from nexus.session_store import atomic_write_json, session_write_lock
from nexus.work_items import (
    list_work_items,
    load_work_item,
    project_work_item_event,
    record_work_item_projection_failure,
    replay_work_item_event_log,
    pending_work_item_projection_failures,
)
from nexus.control_plane import project_plan_event
from nexus.runtime import (
    build_resume_prompt,
    build_chat_request,
    safe_session_id as runtime_safe_session_id,
    session_file_path as runtime_session_file_path,
)
from nexus.task_workflow import complete_task_workflow, start_task_workflow
from nexus.main_agent import NexusLoop
from models.providers.core.reliability import redact_secrets

try:
    import yaml
except Exception:  # pragma: no cover - handled at request time
    yaml = None

# Persistent Safety settings (Permission Mode / Sandbox Mode / policies). Kept
# separate from the workspace selection; see safety.safety_store.
from security.policies.safety_store import (  # noqa: E402
    PERMISSION_MODES as _SAFETY_PERMISSION_MODES,
    SANDBOX_MODES as _SAFETY_SANDBOX_MODES,
    COMMAND_CATEGORIES as _SAFETY_COMMAND_CATEGORIES,
    FILE_POLICY_CATEGORIES as _SAFETY_FILE_POLICY_CATEGORIES,
    FILESYSTEM_OPTIONS as _SAFETY_FILESYSTEM_OPTIONS,
    SECRET_PROTECTION_OPTIONS as _SAFETY_SECRET_PROTECTION_OPTIONS,
    NETWORK_POLICIES as _SAFETY_NETWORK_POLICIES,
    BROWSER_OPTIONS as _SAFETY_BROWSER_OPTIONS,
    MCP_OPTIONS as _SAFETY_MCP_OPTIONS,
    PACKAGE_OPTIONS as _SAFETY_PACKAGE_OPTIONS,
    PACKAGE_MANAGERS as _SAFETY_PACKAGE_MANAGERS,
    PROCESS_OPTIONS as _SAFETY_PROCESS_OPTIONS,
    DESTRUCTIVE_ACTIONS as _SAFETY_DESTRUCTIVE_ACTIONS,
    CHECKPOINT_OPTIONS as _SAFETY_CHECKPOINT_OPTIONS,
)

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ROOT)  # One level up from apps.api/ to project root
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
_WORK_EVENT_STREAM_QUEUE_SIZE = max(32, int(os.environ.get("NEXUS_WORK_EVENT_STREAM_QUEUE_SIZE", "512")))
_CHAT_CHUNK_QUEUE_SIZE = max(16, int(os.environ.get("NEXUS_CHAT_CHUNK_QUEUE_SIZE", "128")))
_CHAT_HEARTBEAT_SECONDS = max(5.0, float(os.environ.get("NEXUS_CHAT_HEARTBEAT_SECONDS", "15")))


def _public_api_failure(operation: str, exc: Exception) -> str:
    """Record a redacted diagnostic and return a stable client-safe message."""
    logger.warning("%s failed: %s", operation, redact_secrets(exc))
    return f"{operation} unavailable"


@contextmanager
def _interprocess_event_lock(path: str):
    """Lock one session's event stream across server worker processes."""
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
_THREAD_LOCAL = threading.local()
_TASKS_PATH = os.path.join(_ROOT, "logs", "tasks.json")
_TASKS_PERSIST_LOCK = threading.RLock()
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configure", "settings.yml")
_CONFIG_MUTATION_LOCK = threading.RLock()
_MCP_SERVERS_PATH = os.path.join(_PROJECT_ROOT, "configure", "mcp_servers.json")
_CLAUDE_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, ".claude", "settings.json")
_CLAUDE_SETTINGS_LOCK = threading.RLock()
_RUNTIME_SETTINGS = {
    "model": "",
    "provider": "",
    "profile": "",
    "mode": "auto",
    "sandbox_tier": "normal",
    "permission_allowlist": [],
    "agent": "",
    "goal": "",
    "additional_dirs": [],
    "workspace_root": "",
    "thinking": True,
    "effort": "medium",
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

# ── Hive runtime state ───────────────────────────────────────────────────────
_HIVES: Dict[str, Dict[str, Any]] = {}
_HIVES_LOCK = threading.Lock()
_HIVE_ENGINE = None
_HIVE_ENGINE_LOCK = threading.Lock()
_HIVE_MANIFEST_PATH = os.path.join(_PROJECT_ROOT, "workspace", "hives", "index.json")
_HIVE_CONSOLIDATION_TASKS: set = set()


def _persist_hive_manifest() -> None:
    """Persist Hive metadata so restart can show interrupted work honestly."""
    with _HIVES_LOCK:
        payload = list(_HIVES.values())
    os.makedirs(os.path.dirname(_HIVE_MANIFEST_PATH), exist_ok=True)
    temporary = f"{_HIVE_MANIFEST_PATH}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _HIVE_MANIFEST_PATH)


async def _consolidate_api_hive(hive_id: str, hive_engine: Any) -> None:
    """Consolidate an API-created hive and persist its result.

    Runs detached so ``POST /api/hives`` can return immediately; the final
    consolidated text (or a consolidation error) is stored on the hive
    manifest entry and surfaced by ``GET /api/hives``.
    """
    try:
        timeout = max(1.0, float(os.environ.get("NEXUS_HIVE_TIMEOUT", "120")))
        consolidated = await hive_engine.consolidate_hive(hive_id, timeout=timeout)
    except asyncio.TimeoutError as exc:
        with _HIVES_LOCK:
            entry = _HIVES.get(hive_id)
            if entry is not None:
                entry["consolidation_error"] = (
                    f"consolidation timed out after {timeout:g}s: {exc}"
                )
        _persist_hive_manifest()
        return
    except Exception as exc:
        logger.warning("hive %s consolidation failed: %s", hive_id, exc, exc_info=True)
        with _HIVES_LOCK:
            entry = _HIVES.get(hive_id)
            if entry is not None:
                entry["consolidation_error"] = str(exc)
        _persist_hive_manifest()
        return
    with _HIVES_LOCK:
        entry = _HIVES.get(hive_id)
        if entry is not None:
            entry["result"] = str(consolidated or "").strip()
            entry["consolidated_at"] = time.time()
    _persist_hive_manifest()


def _load_hive_manifest() -> None:
    """Load prior Hive summaries and mark unfinished processes interrupted."""
    try:
        with open(_HIVE_MANIFEST_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, list):
        return
    with _HIVES_LOCK:
        for item in payload:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            restored = dict(item)
            if restored.get("status") == "running":
                restored["status"] = "interrupted"
                restored["resume_required"] = True
                restored["resume_note"] = "The previous backend stopped before this Hive finished."
                restored["agents"] = [
                    {**agent, "status": "interrupted" if str(agent.get("status") or "").lower() in {"", "pending", "running"} else agent.get("status")}
                    for agent in restored.get("agents", [])
                    if isinstance(agent, dict)
                ]
            _HIVES[str(restored["id"])] = restored


_load_hive_manifest()


def _nonnegative_env_int(name: str, default: int = 0) -> int:
    """Parse an optional bounded integer without making startup fragile."""
    raw = os.getenv(name, str(default))
    try:
        return max(0, int(raw or default))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid integer environment setting %s=%r", name, raw)
        return max(0, int(default))


def _get_hive_engine():
    """Return the process-wide Hive engine used by API-created Hives."""
    global _HIVE_ENGINE
    with _HIVE_ENGINE_LOCK:
        if _HIVE_ENGINE is not None:
            return _HIVE_ENGINE
        from hive.engine import NexusHiveEngine
        from extensions.tools.built_in.nexus_tools.registry import ToolRegistry

        engine = NexusHiveEngine(
            _PROJECT_ROOT,
            tool_registry=ToolRegistry(_PROJECT_ROOT),
            max_total_steps=_nonnegative_env_int("NEXUS_HIVE_MAX_TOTAL_STEPS"),
        )

        def sink(event):
            # API-created Hives have no chat turn, so publish to the default
            # work-event stream. The actual Hive event remains the source of
            # truth; the in-memory summary below is only a compact index.
            try:
                _append_work_event("default", event)
            except Exception:
                logger.debug("Could not persist Hive work event", exc_info=True)
            # Keep the durable Hive index aligned with the event stream.  The
            # index is intentionally only a compact projection; the event log
            # remains the source of truth for detailed transcripts.
            hive_id = str(event.get("hive_id") or "")
            agent_id = str(event.get("related_subagent") or "")
            if hive_id or agent_id:
                changed = False
                with _HIVES_LOCK:
                    for current_id, summary in _HIVES.items():
                        if hive_id and current_id != hive_id:
                            continue
                        for agent in summary.get("agents", []):
                            if agent_id and str(agent.get("id") or "") != agent_id:
                                continue
                            status = str(event.get("status") or "").lower()
                            if status:
                                agent["status"] = status
                                changed = True
                        statuses = {str(a.get("status") or "").lower() for a in summary.get("agents", [])}
                        if statuses and statuses.issubset({"success", "failed", "cancelled", "canceled", "error"}):
                            summary["status"] = "success" if statuses == {"success"} else (
                                "cancelled" if statuses.issubset({"cancelled", "canceled"}) else "failed"
                            )
                            summary["completed_at"] = time.time()
                            changed = True
                if changed:
                    try:
                        _persist_hive_manifest()
                    except Exception:
                        logger.debug("Could not persist Hive event projection", exc_info=True)

        engine.set_sink(sink)
        _HIVE_ENGINE = engine
        return engine

# ── Cron/Scheduler runtime state ───────────────────────────────────────────────
_CRON_JOBS: Dict[str, Dict[str, Any]] = {}
_CRON_JOBS_LOCK = threading.Lock()
_CRON_QUEUE = None
_CRON_TICK_TASK = None
_QUEUE_DRIVER = None
_QUEUE_DRIVER_TASK = None
_QUEUE_DRIVER_STOPPING = False
_HIVE_SUPERVISOR_TASK = None


def _get_cron_queue():
    """Return the project-scoped durable queue used by server cron."""
    global _CRON_QUEUE
    if _CRON_QUEUE is None:
        from queues.store import TaskQueue
        _CRON_QUEUE = TaskQueue(root=_PROJECT_ROOT)
    return _CRON_QUEUE


async def _cron_tick_loop() -> None:
    """Materialize due cron slots; QueueDriver owns actual execution."""
    while True:
        try:
            created = _get_cron_queue().enqueue_due_cron_runs()
            if created:
                logger.info("cron materialized %s due run(s)", len(created))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("cron tick failed", exc_info=True)
        await asyncio.sleep(1.0)


async def _queue_driver_supervisor() -> None:
    """Keep the embedded durable worker alive when the API owns it.

    The API remains useful without this optional worker (for horizontally
    scaled deployments that run a separate ``python -m nexus --autonomous``),
    but a single-process deployment must not silently stop consuming its
    durable queue after a worker-level failure.
    """
    global _QUEUE_DRIVER
    from queues.driver import QueueDriver
    from queues.alerts import dispatch_incident
    from queues.status import clear_incident, read_incident, record_crash

    max_restarts = max(1, int(os.environ.get("NEXUS_QUEUE_MAX_RESTARTS", "5")))
    crash_window = max(1.0, float(os.environ.get("NEXUS_QUEUE_CRASH_WINDOW", "300")))
    if os.environ.get("NEXUS_QUEUE_CLEAR_QUARANTINE", "false").lower() in {"1", "true", "yes", "on"}:
        clear_incident(_PROJECT_ROOT)
    else:
        existing_incident = read_incident(_PROJECT_ROOT)
        if existing_incident.get("quarantined"):
            alert = await asyncio.to_thread(dispatch_incident, _PROJECT_ROOT, existing_incident)
            logger.error(
                "embedded queue worker is quarantined after repeated crashes; operator clearance required (alert=%s)",
                alert.get("status"),
            )
            return

    async def record_failure(error: str) -> bool:
        incident = record_crash(
            _PROJECT_ROOT, error, max_restarts=max_restarts,
            window_seconds=crash_window,
        )
        if incident.get("quarantined"):
            alert = await asyncio.to_thread(dispatch_incident, _PROJECT_ROOT, incident)
            logger.error(
                "embedded queue worker quarantined after %s failures in %.0fs (alert=%s)",
                incident.get("failure_count"), crash_window, alert.get("status"),
            )
            return True
        return False

    backoff = 1.0
    while not _QUEUE_DRIVER_STOPPING:
        try:
            driver = QueueDriver(
                root=_PROJECT_ROOT,
                workers=max(1, int(os.environ.get("NEXUS_QUEUE_WORKERS", "1"))),
                execution_timeout=float(os.environ.get("NEXUS_QUEUE_EXECUTION_TIMEOUT", "3600")),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("embedded queue driver could not initialize; restarting in %.1fs", backoff)
            if await record_failure(str(exc)):
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)
            continue
        _QUEUE_DRIVER = driver
        try:
            await driver.run()
            if _QUEUE_DRIVER_STOPPING:
                return
            logger.error("embedded queue driver exited; restarting in %.1fs", backoff)
            if await record_failure("queue driver exited unexpectedly"):
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("embedded queue driver crashed; restarting in %.1fs", backoff)
            if await record_failure(str(exc)):
                return
        finally:
            if _QUEUE_DRIVER_STOPPING:
                await driver.shutdown(
                    drain_timeout=max(0.0, float(os.environ.get("NEXUS_QUEUE_DRAIN_TIMEOUT", "30")))
                )
        if _QUEUE_DRIVER_STOPPING:
            return
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, 30.0)

# ── Workspace checkpoints ────────────────────────────────────────────────────
# Per-message restore points: a snapshot of the workspace taken right before a
# run's first tool executes, so the GUI can revert file changes made by a turn.
# Stored outside the snapshot scope (the workspace/ dir is ignored while walking).
_CHECKPOINTS_ROOT = os.path.join(_PROJECT_ROOT, "workspace", "checkpoints")
# Heavy/generated/app-runtime paths never enter a checkpoint snapshot. This keeps
# snapshots small and fast, and guarantees restore never touches those areas.
# ``workspace/`` itself is the default snapshot root, so its internal stores
# (checkpoints, work events) must be excluded by name or every snapshot copies
# all prior checkpoints and a restore can delete newer ones.
_CHECKPOINT_SKIP_NAMES = frozenset({
    ".git", ".venv", ".voice-venv", ".research", ".kilo", ".opencode", ".tmp",
    ".cache", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox",
    ".playwright-cli", ".playwright-mcp", ".nexus", "workspace", "models",
    "bin", "logs", "graphify-out", "queue", "dist", "build", "node_modules",
    "__pycache__", ".idea", ".vscode", ".next", "coverage", "htmlcov", "deploy",
    "checkpoints", "work_events",
})
_CHECKPOINT_SKIP_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".pyd", ".gguf", ".safetensors",
    ".onnx", ".pt", ".pth", ".bin", ".pkl",
})
_CHECKPOINT_GUARD: Dict[str, str] = {}
_CHECKPOINT_GUARD_LOCK = threading.Lock()
_CHECKPOINT_RESTORE_LOCKS: Dict[str, "threading.Lock"] = {}
_CHECKPOINT_RESTORE_LOCKS_LOCK = threading.Lock()
_CHECKPOINT_STREAM_PUSHERS: Dict[str, Any] = {}
_CHECKPOINT_STREAM_PUSHERS_LOCK = threading.Lock()


def _validate_public_deployment() -> None:
    """Fail closed when the operator explicitly marks this as public.

    Local development keeps its convenient defaults, but a process intended
    for internet exposure must not start with anonymous auth, unrestricted
    execution, or a localhost-only CORS policy.
    """
    enabled = os.environ.get("NEXUS_PUBLIC_DEPLOYMENT", "false").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return
    errors = []
    from security.core.auth import OAUTH_PROVIDERS

    token = os.environ.get("NEXUS_DASHBOARD_TOKEN", "").strip()
    if not token and not OAUTH_PROVIDERS:
        errors.append("NEXUS_DASHBOARD_TOKEN or OAuth credentials are required")
    elif token and len(token) < 32:
        errors.append("NEXUS_DASHBOARD_TOKEN must be at least 32 characters")
    if len(os.environ.get("NEXUS_SESSION_SECRET", "").strip()) < 32:
        errors.append("NEXUS_SESSION_SECRET must be configured with at least 32 characters")
    if os.environ.get("NEXUS_ALLOW_LOCAL_ANON", "false").lower() == "true":
        errors.append("NEXUS_ALLOW_LOCAL_ANON must be false")
    if os.environ.get("NEXUS_SANDBOX_TIER", "normal").strip().lower() not in {"normal", "docker"}:
        errors.append("NEXUS_SANDBOX_TIER must be normal or docker")
    origins = [item.strip() for item in os.environ.get("NEXUS_CORS_ORIGINS", "").split(",") if item.strip()]
    if (
        not origins
        or any(
            item == "*"
            or not item.lower().startswith("https://")
            or "localhost" in item
            or "127.0.0.1" in item
            for item in origins
        )
    ):
        errors.append("NEXUS_CORS_ORIGINS must contain only HTTPS production origins")
    if errors:
        raise RuntimeError("Public deployment validation failed: " + "; ".join(errors))


async def _auto_resume_interrupted_hives() -> List[str]:
    """Resume interrupted Hive work once during an opted-in server boot.

    Auto-resume is opt-in because replaying an agent task can repeat an
    external side effect. Only manifests explicitly marked ``resume_required``
    (created by crash recovery) are eligible, and ``resume_hive`` already
    filters terminal agents and creates a new linked Hive identity.
    """
    with _HIVES_LOCK:
        candidates = [
            str(hive_id) for hive_id, summary in _HIVES.items()
            if summary.get("resume_required")
            and str(summary.get("status") or "").lower() in {"interrupted", "failed"}
        ]
    resumed: List[str] = []
    for hive_id in candidates:
        try:
            result = await resume_hive(hive_id)
            new_id = str((result.get("hive") or {}).get("id") or "")
            if new_id:
                resumed.append(new_id)
        except HTTPException as exc:
            logger.warning("Hive %s was not auto-resumed (%s)", hive_id, exc.detail)
        except Exception:
            logger.exception("Hive %s auto-resume failed", hive_id)
    return resumed


async def _hive_supervisor_loop() -> None:
    """Continuously replace Hive agents that stop heartbeating."""
    interval = max(2.0, float(os.environ.get("NEXUS_HIVE_SUPERVISOR_INTERVAL", "15")))
    stale_after = max(interval * 2.0, float(os.environ.get("NEXUS_HIVE_STALE_AFTER", "120")))
    while True:
        try:
            engine = _get_hive_engine()
            await engine.recover_stuck_agents(stale_after=stale_after)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hive supervisor iteration failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Join response-detached learning tasks before asyncio tears down."""
    global _CRON_TICK_TASK, _QUEUE_DRIVER, _QUEUE_DRIVER_TASK, _QUEUE_DRIVER_STOPPING, _HIVE_SUPERVISOR_TASK, _HIVE_ENGINE
    _validate_public_deployment()
    _warm_workspace_summary()
    if os.environ.get("NEXUS_HIVE_AUTO_RESUME", "true").lower() in {"1", "true", "yes", "on"}:
        await _auto_resume_interrupted_hives()
    _QUEUE_DRIVER_STOPPING = False
    _CRON_TICK_TASK = asyncio.create_task(_cron_tick_loop())
    if _embed_queue_driver_enabled():
        _QUEUE_DRIVER_TASK = asyncio.create_task(_queue_driver_supervisor())
    if os.environ.get("NEXUS_HIVE_STUCK_RECOVERY", "true").lower() in {"1", "true", "yes", "on"}:
        _HIVE_SUPERVISOR_TASK = asyncio.create_task(_hive_supervisor_loop())
    yield
    _QUEUE_DRIVER_STOPPING = True
    if _QUEUE_DRIVER is not None:
        _QUEUE_DRIVER.stop()
    if _QUEUE_DRIVER_TASK is not None and not _QUEUE_DRIVER_TASK.done():
        try:
            await asyncio.wait_for(
                _QUEUE_DRIVER_TASK,
                timeout=max(1.0, float(os.environ.get("NEXUS_QUEUE_DRAIN_TIMEOUT", "30"))) + 5.0,
            )
        except asyncio.TimeoutError:
            _QUEUE_DRIVER_TASK.cancel()
            await asyncio.gather(_QUEUE_DRIVER_TASK, return_exceptions=True)
    _QUEUE_DRIVER_TASK = None
    _QUEUE_DRIVER = None
    if _HIVE_SUPERVISOR_TASK is not None and not _HIVE_SUPERVISOR_TASK.done():
        _HIVE_SUPERVISOR_TASK.cancel()
        await asyncio.gather(_HIVE_SUPERVISOR_TASK, return_exceptions=True)
    _HIVE_SUPERVISOR_TASK = None
    pending_consolidations = [t for t in _HIVE_CONSOLIDATION_TASKS if not t.done()]
    for task in pending_consolidations:
        task.cancel()
    if pending_consolidations:
        await asyncio.gather(*pending_consolidations, return_exceptions=True)
    _HIVE_CONSOLIDATION_TASKS.clear()
    with _HIVE_ENGINE_LOCK:
        hive_engine, _HIVE_ENGINE = _HIVE_ENGINE, None
    if hive_engine is not None:
        try:
            await asyncio.wait_for(
                hive_engine.aclose(),
                timeout=max(1.0, float(os.environ.get("NEXUS_HIVE_DRAIN_TIMEOUT", "15"))),
            )
        except asyncio.TimeoutError:
            logger.error("Hive engine shutdown exceeded its bounded drain timeout")
        except Exception:
            logger.exception("Hive engine shutdown failed")
    if _CRON_TICK_TASK is not None and not _CRON_TICK_TASK.done():
        _CRON_TICK_TASK.cancel()
        await asyncio.gather(_CRON_TICK_TASK, return_exceptions=True)
    _CRON_TICK_TASK = None
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

from security.core.auth import _SESSION_SECRET as _session_secret

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
from security.core.auth import AuthUser, check_auth, is_loopback_request

_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", "com1", "com2", "com3", "com4",
    "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
    "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"})

_AUTH_SKIP_PATHS = frozenset({
    "/api/health", "/api/auth/login", "/api/auth/callback",
    "/api/auth/token", "/api/logout", "/api/auth/status",
    "/api/version",
})

_RATE_BUCKETS: Dict[str, List[float]] = {}
_RATE_BUCKETS_LOCK = threading.Lock()
try:
    _RATE_WINDOW_SECONDS = max(1.0, float(os.environ.get("NEXUS_RATE_WINDOW_SECONDS", "60")))
except (TypeError, ValueError):
    _RATE_WINDOW_SECONDS = 60.0
try:
    _RATE_LIMIT = max(10, int(os.environ.get("NEXUS_RATE_LIMIT", "120")))
except (TypeError, ValueError):
    _RATE_LIMIT = 120


def _server_rate_limited(client: str) -> bool:
    """Apply a bounded per-peer request limit before expensive routes run.

    This is a process-local guardrail; public deployments should still place
    a shared limiter at the reverse proxy/load-balancer boundary.
    """
    now = time.time()
    with _RATE_BUCKETS_LOCK:
        bucket = [stamp for stamp in _RATE_BUCKETS.get(client, []) if now - stamp < _RATE_WINDOW_SECONDS]
        bucket.append(now)
        _RATE_BUCKETS[client] = bucket
        return len(bucket) > _RATE_LIMIT

if os.environ.get("NEXUS_PUBLIC_OPENAI_COMPAT", "false").lower() == "true":
    _AUTH_SKIP_PATHS = frozenset((*_AUTH_SKIP_PATHS, "/v1/models", "/v1/chat/completions"))


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    client = request.client.host if request.client else "unknown"
    if path != "/api/health" and _server_rate_limited(client):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(int(_RATE_WINDOW_SECONDS))},
        )
    if path in _AUTH_SKIP_PATHS:
        return await call_next(request)

    # NEXUS_ALLOW_LOCAL_ANON is an explicit opt-in used by local/test clients
    # (and the pytest suite via TestClient, whose peer host is the literal
    # string "testclient" rather than a real loopback address). It is OFF by
    # default and MUST stay that way. When enabled it is ALSO restricted to
    # genuine loopback peers — without that, the flag would silently disable
    # auth for any client that could reach the port (LAN, tunnels, bridges).
    if os.environ.get("NEXUS_ALLOW_LOCAL_ANON", "false").lower() == "true" and is_loopback_request(request):
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

    from security.core.auth import OAUTH_PROVIDERS, get_oauth_authorize_url

    oauth = OAUTH_PROVIDERS.get(provider)
    if not oauth:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    configured_base = os.environ.get("NEXUS_API_BASE", "http://127.0.0.1:8000")
    if redirect:
        # Only loopback or the configured API origin may be used as the OAuth
        # redirect target; an attacker-controlled redirect_uri could capture
        # authorization codes with a loosely registered provider client.
        try:
            parsed = urllib.parse.urlparse(redirect)
        except Exception:
            parsed = None
        if parsed and parsed.scheme in ("http", "https") and parsed.netloc:
            loopback_ok = parsed.hostname in ("127.0.0.1", "localhost", "::1")
            same_origin = redirect.rstrip("/") == configured_base.rstrip("/")
            if not (loopback_ok or same_origin):
                raise HTTPException(status_code=400, detail="redirect must be loopback or the configured API origin")
        elif parsed and parsed.path and not redirect.startswith(("/", "?")):
            raise HTTPException(status_code=400, detail="redirect must be a relative path or loopback URL")

    base_redirect = redirect or f"{configured_base}/api/auth/callback"
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

    from security.core.auth import handle_oauth_callback
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
    from security.core.auth import validate_dashboard_token

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
            from security.core.auth import validate_dashboard_token
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
    # Never reflect arbitrary exception text to API clients.  Provider errors,
    # paths, command lines, and credentials can all be embedded in it.  Keep a
    # redacted diagnostic in server logs while returning a stable contract.
    logger.warning("Unhandled API exception: %s", redact_secrets(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
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


def _safe_event_sequence(event: Dict[str, Any], default: int = 0) -> int:
    """Normalize untrusted persisted sequence values for all read paths."""
    try:
        value = int(event.get("sequence") or default)
    except (AttributeError, TypeError, ValueError):
        return max(0, int(default or 0))
    return max(0, value)


def _next_work_event_sequence_unlocked(path: str) -> int:
    """Return a restart-safe monotonic sequence for one persisted work stream."""
    with _WORK_EVENT_SEQUENCE_LOCK:
        # Reconcile the persisted high-water mark while holding the
        # cross-process mutex. A worker's in-memory cache may be stale after a
        # different worker appended records.
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
    """Allocate a sequence while holding both process and OS-level locks."""
    with _interprocess_event_lock(path):
        return _next_work_event_sequence_unlocked(path)


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


def _is_sensitive_workspace_path(path: str) -> bool:
    """Identify files that must never be returned by a remote file API."""
    root = os.path.realpath(os.path.abspath(_PROJECT_ROOT))
    candidate = os.path.realpath(os.path.abspath(path))
    try:
        relative = os.path.relpath(candidate, root).replace("\\", "/")
    except (ValueError, OSError):
        return True
    parts = [part.lower() for part in relative.split("/")]
    name = parts[-1] if parts else ""
    return (
        name == ".env"
        or name.startswith(".env.")
        or name.endswith((".pem", ".key"))
        or ".ssh" in parts
        or "credential" in name
        or "secret" in name
    )


def safe_workspace_read_path(raw_path: str) -> str:
    value = str(raw_path or "").strip().strip('"').strip("'")
    if not value:
        raise HTTPException(status_code=400, detail="Path is required")
    if not os.path.isabs(value):
        value = os.path.join(_PROJECT_ROOT, value)
    root = os.path.realpath(os.path.abspath(_PROJECT_ROOT))
    path = os.path.realpath(os.path.abspath(value))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=400, detail="Path is outside the NEXUS workspace")
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    if _is_sensitive_workspace_path(path):
        raise HTTPException(status_code=403, detail="Sensitive files cannot be read through the API")
    return path


def write_workspace_todo_plan(content: str) -> str:
    """Persist the visible agent plan as a real workspace file (atomic)."""
    from extensions.tools.built_in.planning.scripts.planning import plan_transaction

    workspace_dir = os.path.join(_PROJECT_ROOT, "workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    todo_path = os.path.abspath(os.path.join(workspace_dir, "todo.md"))
    if os.path.commonpath([os.path.abspath(workspace_dir), todo_path]) != os.path.abspath(workspace_dir):
        raise HTTPException(status_code=400, detail="Invalid todo path")
    with plan_transaction(_PROJECT_ROOT):
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
    return os.path.relpath(todo_path, _PROJECT_ROOT)



# ── Plan / todo workflow (ported from the canonical gui.api implementation) ──
def clear_workspace_todo_plan() -> None:
    from extensions.tools.built_in.planning.scripts.planning import plan_transaction

    try:
        with plan_transaction(_PROJECT_ROOT):
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
            raw_events = []
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(event, dict):
                        raw_events.append(event)
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
        list_events=lambda sid, tid: list_work_events(sid, limit=1000, turn_id=tid),
        append_event=append_work_event,
        write_plan=write_workspace_todo_plan,
    )


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


def configured_provider_defaults() -> tuple[str, str]:
    """Return the configured provider/model without treating ``auto`` as one.

    TUI clients intentionally send an empty or ``auto`` selection until a user
    picks an override. The server must resolve that state through provider.yml
    rather than letting the model router choose an unrelated fallback.
    """
    try:
        from configure.config_loader import NexusConfigLoader
        loader = NexusConfigLoader()
        provider_cfg = loader.get("provider", {})
        if not isinstance(provider_cfg, dict):
            return "", ""
        provider_name = str(provider_cfg.get("default_provider") or "").strip().lower()
        providers = provider_cfg.get("providers", {})
        provider_data = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
        model = str(provider_data.get("model") or "").strip() if isinstance(provider_data, dict) else ""
        return provider_name, model
    except Exception:
        logger.debug("Configured provider defaults unavailable", exc_info=True)
        return "", ""


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
    with _WORK_EVENT_APPEND_LOCK, _interprocess_event_lock(path):
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

    # Keep the durable verifier ledger aligned with API-originated file
    # mutations as well as V5 tool events. Reads never invalidate a verdict.
    if event.get("kind") == "file" and str(event.get("status") or "").lower() in {
        "completed", "success", "done"
    }:
        action_text = str(event.get("action") or "").lower()
        if any(token in action_text for token in ("edit", "create", "write", "delete", "remove", "update")):
            try:
                from nexus.main_agent.verification_state import VerifierStateStore

                state_path = Path(_PROJECT_ROOT) / ".nexus_v5" / "verifier_state.json"
                VerifierStateStore(state_path).mark_stale(
                    event["conversation_id"], _PROJECT_ROOT, [event.get("path") or target]
                )
            except Exception:
                logger.debug("Could not invalidate verifier state for file event", exc_info=True)

    # Project only the persisted canonical/public event.  The projector is
    # deliberately append-free, so this cannot recursively write events.
    try:
        project_work_item_event(root=_RUN_ROOT, session_id=event["conversation_id"], event=event)
        project_plan_event(root=_RUN_ROOT, session_id=event["conversation_id"], event=event)
    except Exception as exc:
        logger.debug("Could not project work event onto WorkItem", exc_info=True)
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

    _maybe_trigger_checkpoint(session_id, event)
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
    raw_events = _session_work_events(session_id)
    for event in raw_events:
        if str(event.get("visibility", "")).lower() == "internal":
            continue
        if _safe_event_sequence(event) > after_sequence:
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
        run_key = str(enriched.get("run_id") or turn_id or "")
        if run_key:
            if str(enriched.get("event_type") or "") in (
                "run.completed",
                "run.failed",
                "run.cancelled",
                "run.timed_out",
            ):
                _unregister_checkpoint_pusher(run_key)
            else:
                _register_checkpoint_pusher(run_key, lambda evt: out_queue.put(("event", evt)))
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
    # Every persisted event needs a stable identity so lifecycle updates (for
    # example command running -> success) collapse into one timeline record.
    # The legacy server path previously allowed anonymous command events,
    # which made its start and terminal records appear twice.
    event_id = str(payload.get("event_id") or payload.get("id") or f"evt_{uuid.uuid4().hex}")
    payload["event_id"] = event_id
    payload["id"] = event_id
    path = work_events_path(sid)
    with _WORK_EVENT_APPEND_LOCK, _interprocess_event_lock(path):
        if not payload.get("sequence"):
            payload["sequence"] = _next_work_event_sequence_unlocked(path)
        else:
            try:
                sequence = int(payload.get("sequence") or 0)
                allocate_replacement = False
                with _WORK_EVENT_SEQUENCE_LOCK:
                    current = _WORK_EVENT_SEQUENCES.get(path, 0)
                    if sequence <= current:
                        payload["source_sequence"] = sequence
                        # Do not allocate while holding the non-reentrant
                        # sequence lock.  The allocator acquires that lock
                        # itself; terminal command events commonly copy the
                        # started event's sequence and used to deadlock here.
                        allocate_replacement = True
                    else:
                        _WORK_EVENT_SEQUENCES[path] = sequence
                if allocate_replacement:
                    payload["sequence"] = _next_work_event_sequence_unlocked(path)
            except (TypeError, ValueError):
                payload["sequence"] = _next_work_event_sequence_unlocked(path)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    try:
        project_work_item_event(root=_RUN_ROOT, session_id=sid, event=payload)
        project_plan_event(root=_RUN_ROOT, session_id=sid, event=payload)
    except Exception as exc:
        logger.debug("Could not project legacy work event onto WorkItem", exc_info=True)
        record_work_item_projection_failure(
            event_log_path=work_events_path(sid),
            event=payload,
            error=exc,
        )
    _maybe_trigger_checkpoint(sid, payload)
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
    raw_events = _session_work_events(session_id)

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
        if event_type.startswith("run.") and (
            status in {"success", "failed", "cancelled", "canceled", "timed_out", "error"}
            or event_type == "run.timed_out"
        ):
            terminal_event = event_type
    return {
        "event_count": len(events),
        "last_sequence": last_sequence,
        "statuses": statuses,
        "kinds": kinds,
        "terminal_event": terminal_event,
    }


def _public_run_event_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit must be an integer") from exc
    if value < 1 or value > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    return value


def list_public_run_events(session_id: str, run_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """Return bounded append-only public events for one run without collapsing ids."""
    safe_limit = _public_run_event_limit(limit)
    raw_events = _session_work_events(session_id)
    events: List[Dict[str, Any]] = []
    for event in raw_events:
        if str(event.get("visibility") or "public").lower() == "internal":
            continue
        if _is_private_diagnostic_event(event):
            continue
        if str(event.get("turn_id") or event.get("run_id") or "") != str(run_id):
            continue
        events.append(event)
        if len(events) >= safe_limit:
            break
    return events


def get_loop(session_id: str = "default") -> NexusLoop:
    sid = safe_session_id(session_id)
    if sid not in _LOOPS:
        loop = NexusLoop(root_dir=_PROJECT_ROOT, session_id=sid)
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
        from nexus.common.session_bus import set_active_session_id
        set_active_session_id(_PROJECT_ROOT, session_id, source=source)
    except Exception as e:
        logger.warning("set_active_session: failed for %s: %s", session_id, e)


_CHAT_SESSION_GUARD_LOCK = threading.Lock()
_CHAT_SESSION_GUARDS: Dict[str, asyncio.Lock] = {}


def _chat_session_guard(session_id: str) -> asyncio.Lock:
    """Per-session asyncio lock that makes the ``/api/chat`` run-start check
    atomic. ``stream_run`` serializes runs through its own run guard, but the
    route's ``is_running`` check happens long before that guard is acquired;
    without this lock two concurrent requests for the same session can both
    pass the check and both start a run."""
    with _CHAT_SESSION_GUARD_LOCK:
        guard = _CHAT_SESSION_GUARDS.get(session_id)
        if guard is None:
            guard = asyncio.Lock()
            _CHAT_SESSION_GUARDS[session_id] = guard
        return guard


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
    profile = str(_RUNTIME_SETTINGS.get("profile") or "").strip()
    mode = _normalize_permission_mode(str(_RUNTIME_SETTINGS.get("mode") or "auto"))
    sandbox_tier = _normalize_sandbox_tier(str(_RUNTIME_SETTINGS.get("sandbox_tier") or "normal"))
    agent = str(_RUNTIME_SETTINGS.get("agent") or "").strip()
    goal = str(_RUNTIME_SETTINGS.get("goal") or "").strip()
    additional_dirs = _RUNTIME_SETTINGS.get("additional_dirs") or []
    allowlist = [str(item).strip() for item in (_RUNTIME_SETTINGS.get("permission_allowlist") or []) if str(item).strip()]

    loop.model = model
    loop.provider_override = provider
    loop.profile_override = profile or None
    loop.permission_mode = mode
    loop.active_agent = agent
    loop.active_goal = goal
    loop.additional_dirs = [str(item) for item in additional_dirs if str(item).strip()]
    loop.checklist = set(allowlist) or getattr(loop, "checklist", set())

    if provider:
        try:
            loop.brain.set_override(provider, profile or None)
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
        from security.permissions import PermissionMode
        from nexus.main_agent.core import PermissionPolicy
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

    # Coordinate with V5/MemoryManager writers across API workers.  Persist
    # the cleared transcript while holding the same lock used by normal saves;
    # updating the cached loop afterwards avoids a nested lock acquisition.
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
        raise HTTPException(status_code=500, detail="settings.yml must contain a mapping")
    return data


def _save_nexus_config(config: Dict[str, Any]) -> None:
    _require_yaml()
    directory = os.path.dirname(_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, width=100)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _CONFIG_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _mutate_nexus_config_sync(mutator):
    """Reload, mutate, and persist settings as one cross-process transaction."""
    with _CONFIG_MUTATION_LOCK, _interprocess_event_lock(_CONFIG_PATH):
        config = _load_nexus_config()
        result = mutator(config)
        _save_nexus_config(config)
        return result


def _create_mcp_config_sync(name: str, entry: Dict[str, Any]) -> None:
    """Update both MCP configuration stores under one settings transaction."""
    with _CONFIG_MUTATION_LOCK, _interprocess_event_lock(_CONFIG_PATH):
        config = _load_nexus_config()
        servers = config.setdefault("mcp_servers", {})
        if not isinstance(servers, dict):
            servers = {}
            config["mcp_servers"] = servers
        servers[name] = entry
        _save_nexus_config(config)
        _sync_mcp_servers_file(config)


def _sync_mcp_servers_file(config: Dict[str, Any]) -> None:
    """Keep the registry's JSON MCP source synchronized with UI YAML settings."""
    raw_servers = config.get("mcp_servers") if isinstance(config, dict) else {}
    if not isinstance(raw_servers, dict):
        raw_servers = {}
    servers = []
    for name, raw in sorted(raw_servers.items()):
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        entry["name"] = str(name)
        entry["command"] = str(entry.get("command") or entry.get("cmd") or "").strip()
        args = entry.get("args", [])
        if isinstance(args, str):
            args = [part for part in args.splitlines() if part.strip()]
        entry["args"] = [str(part) for part in args] if isinstance(args, list) else []
        entry["active"] = bool(entry.get("active", True))
        if not entry["command"]:
            continue
        servers.append(entry)
    payload = {
        "_note": "MCP servers to auto-start with NEXUS. Each server must have a command and args.",
        "servers": servers,
    }
    os.makedirs(os.path.dirname(_MCP_SERVERS_PATH), exist_ok=True)
    temporary = f"{_MCP_SERVERS_PATH}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, _MCP_SERVERS_PATH)


def _load_runtime_preferences() -> None:
    try:
        config = _load_nexus_config()
        runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        if "permission_mode" in runtime:
            _RUNTIME_SETTINGS["mode"] = _normalize_permission_mode(str(runtime.get("permission_mode") or "auto"))
        if "sandbox_tier" in runtime:
            _RUNTIME_SETTINGS["sandbox_tier"] = _normalize_sandbox_tier(str(runtime.get("sandbox_tier") or "normal"))
            os.environ["NEXUS_SANDBOX_TIER"] = str(_RUNTIME_SETTINGS["sandbox_tier"])
        if "thinking" in runtime:
            _RUNTIME_SETTINGS["thinking"] = bool(runtime.get("thinking", True))
        if "effort" in runtime:
            _RUNTIME_SETTINGS["effort"] = str(runtime.get("effort") or "medium").strip().lower()
        if "model" in runtime:
            _RUNTIME_SETTINGS["model"] = str(runtime.get("model") or "").strip()
        if "provider" in runtime:
            _RUNTIME_SETTINGS["provider"] = str(runtime.get("provider") or "").strip()
        if "profile" in runtime:
            _RUNTIME_SETTINGS["profile"] = str(runtime.get("profile") or "").strip()
        allowlist = runtime.get("permission_allowlist")
        if isinstance(allowlist, list):
            _RUNTIME_SETTINGS["permission_allowlist"] = [str(item).strip() for item in allowlist if str(item).strip()]
        if "additional_dirs" in runtime:
            raw_dirs = runtime.get("additional_dirs")
            if isinstance(raw_dirs, list):
                _RUNTIME_SETTINGS["additional_dirs"] = [str(item).strip() for item in raw_dirs if str(item).strip()]
        if "workspace_root" in runtime:
            _RUNTIME_SETTINGS["workspace_root"] = str(runtime.get("workspace_root") or "").strip()
    except Exception:
        logger.warning("load_runtime_preferences: failed", exc_info=True)


def _save_runtime_preferences() -> None:
    try:
        def mutate(config):
            runtime = config.setdefault("runtime", {})
            if not isinstance(runtime, dict):
                runtime = {}
                config["runtime"] = runtime
            runtime["permission_mode"] = _normalize_permission_mode(_RUNTIME_SETTINGS.get("mode") or "auto")
            runtime["permission_allowlist"] = list(_RUNTIME_SETTINGS.get("permission_allowlist") or [])
            runtime["sandbox_tier"] = _normalize_sandbox_tier(_RUNTIME_SETTINGS.get("sandbox_tier") or "normal")
            runtime["thinking"] = bool(_RUNTIME_SETTINGS.get("thinking", True))
            runtime["effort"] = str(_RUNTIME_SETTINGS.get("effort") or "medium").strip().lower()
            runtime["model"] = str(_RUNTIME_SETTINGS.get("model") or "").strip()
            runtime["provider"] = str(_RUNTIME_SETTINGS.get("provider") or "").strip()
            runtime["profile"] = str(_RUNTIME_SETTINGS.get("profile") or "").strip()
            runtime["additional_dirs"] = list(_RUNTIME_SETTINGS.get("additional_dirs") or [])
            workspace_root = str(_RUNTIME_SETTINGS.get("workspace_root") or "").strip()
            if workspace_root:
                runtime["workspace_root"] = workspace_root

        _mutate_nexus_config_sync(mutate)
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
    directory = os.path.dirname(_CLAUDE_SETTINGS_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".claude-settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _CLAUDE_SETTINGS_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _mutate_claude_settings_sync(mutator) -> Any:
    """Reload and persist Claude plugin settings under one cross-process lock."""
    with _CLAUDE_SETTINGS_LOCK, _interprocess_event_lock(_CLAUDE_SETTINGS_PATH):
        settings = _load_claude_settings(strict=True)
        result = mutator(settings)
        _save_claude_settings(settings)
        return result


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
    if not isinstance(providers, dict) or not providers:
        # Auto-generate providers from factory mappings if config doesn't have providers section
        try:
            from models.providers.core.factory import MAPPINGS
            providers = {
                "cloud": {},
                "local": {},
                "oauth": {}
            }
            for provider_id, (module_path, class_name) in MAPPINGS.items():
                # Determine group based on provider type
                if provider_id in ["ollama", "lm_studio", "llama_cpp", "vllm", "sglang"]:
                    group = "local"
                elif provider_id in ["claude", "github_copilot", "codex", "minimax", "chutes", "grok"]:
                    group = "oauth"
                else:
                    group = "cloud"
                
                if group not in providers:
                    providers[group] = {}
                
                providers[group][provider_id] = {
                    "active": False,
                    "model": "",
                    "endpoint": ""
                }
        except Exception:
            return rows
    
    for group_name, group in providers.items():
        if not isinstance(group, dict):
            continue
        for name, entry in group.items():
            if not isinstance(entry, dict):
                continue
            rows.append({
                "id": name,
                "name": name,
                "group": group_name,
                "active": bool(entry.get("active", False)),
                "model": entry.get("model", ""),
                "endpoint": entry.get("endpoint", ""),
                "available": True,
                "configured": bool(entry.get("active", False)) or bool(entry.get("model", "")) or bool(entry.get("endpoint", "")),
                "description": f"{group_name} provider",
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
    with _TASKS_PERSIST_LOCK, _interprocess_event_lock(_TASKS_PATH):
        directory = os.path.dirname(_TASKS_PATH)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tasks-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _TASKS_PATH)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def _clear_runtime(reason: str) -> Dict[str, Any]:
    global _HIVE_ENGINE
    count = len(_LOOPS)
    _LOOPS.clear()
    # ToolRegistry and Hive are process-wide caches.  Clearing only session
    # loops leaves newly-added MCP tools invisible until a full restart.
    refreshed = False
    try:
        from nexus.runtime.kernel import NexusKernel
        kernel = NexusKernel(_PROJECT_ROOT)
        cached_registry = getattr(kernel, "_instances", {}).pop("tools", None)
        if cached_registry is not None:
            close = getattr(cached_registry, "close", None)
            if callable(close):
                close()
            refreshed = True
        getattr(kernel, "_instances", {}).pop("hive", None)
        _HIVE_ENGINE = None
    except Exception as exc:
        logger.debug("Runtime tool cache refresh failed: %s", exc)
    return {"reloaded_loops": count, "tool_registry_refreshed": refreshed, "reason": reason}


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
        args = entry.get("args", [])
        if isinstance(args, list):
            args_str = " ".join(str(a) for a in args)
        else:
            args_str = str(args)
        mcp.append({
            "id": name,
            "description": str(entry.get("description", ""))[:120],
            "active": bool(entry.get("active", False)),
            "command": entry.get("command", ""),
            "args": args_str,
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

def _provider_reachability(provider_name: str) -> Dict[str, Any]:
    """Report configured-vs-reachable state without probing cloud providers.

    Local providers are checked at the TCP level so the status endpoint cannot
    claim LM Studio is healthy merely because the Nexus API process is alive.
    Remote providers remain ``unknown`` here; their credentials, quotas, and
    model availability are validated by the actual model request.
    """
    name = str(provider_name or "").strip().lower()
    if name in {"auto", "", "unknown"}:
        return {"name": name or "auto", "configured": False, "reachable": None, "reason": "provider_not_selected"}
    try:
        from models.providers.core.factory import NexusProviderFactory

        factory = NexusProviderFactory()
        provider = factory.get_provider_by_name("cloud", name)
        if provider is None:
            return {"name": name, "configured": False, "reachable": False, "reason": "provider_not_configured"}
        endpoint = str(getattr(provider, "endpoint", "") or "")
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        is_local = name in {"lm_studio", "lm-studio", "ollama", "local"} or host in {"127.0.0.1", "localhost", "::1"}
        if not is_local:
            return {"name": name, "configured": True, "reachable": None, "reason": "remote_probe_deferred"}
        if not host:
            return {"name": name, "configured": True, "reachable": False, "reason": "invalid_local_endpoint", "endpoint": endpoint}
        try:
            with socket.create_connection((host, port), timeout=0.8):
                reachable = True
        except OSError:
            reachable = False
        return {
            "name": name,
            "configured": True,
            "reachable": reachable,
            "reason": "reachable" if reachable else "local_server_unreachable",
            "endpoint": endpoint,
        }
    except Exception as exc:
        logger.debug("Provider reachability check failed: %s", exc)
        return {"name": name, "configured": True, "reachable": None, "reason": "probe_failed"}


def _provider_runtime_diagnostics() -> Dict[str, Any]:
    """Return bounded, secret-free provider routing diagnostics.

    Provider credentials and raw exceptions never cross this boundary.  The
    router already records classified attempts, while the profile store owns
    cooldown state; this helper only projects those two sources for status
    consumers.  It is deliberately best-effort because status must remain
    available when a provider subsystem is unavailable.
    """
    attempts: List[Dict[str, Any]] = []
    latest = list(_LOOPS.values())[-1] if _LOOPS else None
    routers: List[Any] = []
    try:
        brain = getattr(latest, "brain", None)
        if brain is not None:
            routers.extend([brain, getattr(brain, "base_router", None)])
    except Exception:
        pass
    seen_routers = set()
    for router in routers:
        if router is None or id(router) in seen_routers:
            continue
        seen_routers.add(id(router))
        try:
            getter = getattr(router, "provider_attempts", None)
            if callable(getter):
                value = getter()
                if isinstance(value, list):
                    try:
                        from models.providers.core.reliability import redact_secrets
                    except Exception:
                        redact_secrets = lambda value: str(value or "")
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        # Whitelist the public schema; never pass through
                        # credential IDs or arbitrary provider payload fields.
                        attempts.append({
                            "provider_id": str(item.get("provider_id") or "")[:80],
                            "profile": str(item.get("profile") or "")[:80],
                            "model": str(item.get("model") or "")[:160],
                            "attempt": max(1, int(item.get("attempt") or 1)),
                            "status": str(item.get("status") or "")[:32],
                            "failure_class": str(item.get("failure_class") or "")[:64],
                            "strategy": str(item.get("strategy") or "")[:64],
                            "reason": redact_secrets(str(item.get("reason") or ""))[:240],
                            "duration_ms": round(max(0.0, float(item.get("duration_ms") or 0.0)), 3),
                            "timestamp": item.get("timestamp"),
                        })
        except Exception:
            logger.debug("Provider attempt diagnostics unavailable", exc_info=True)

    # The recorder is bounded, but cap the API projection independently so a
    # future router implementation cannot accidentally make status payloads
    # unbounded.
    attempts = attempts[-32:]
    last_failure = None
    for item in reversed(attempts):
        if str(item.get("status") or "").lower() in {"failed", "error"}:
            last_failure = {
                "provider": str(item.get("provider_id") or "")[:80],
                "profile": str(item.get("profile") or "")[:80],
                "model": str(item.get("model") or "")[:160],
                "failure_class": str(item.get("failure_class") or "")[:64],
                "strategy": str(item.get("strategy") or "")[:64],
                "reason": str(item.get("reason") or "")[:240],
                "timestamp": item.get("timestamp"),
            }
            break

    selected = None
    for item in reversed(attempts):
        if str(item.get("status") or "").lower() in {"success", "succeeded", "completed"}:
            selected = {
                "provider": str(item.get("provider_id") or "")[:80],
                "profile": str(item.get("profile") or "")[:80],
                "model": str(item.get("model") or "")[:160],
            }
            break
    if selected is None:
        selected = {
            "provider": str(_RUNTIME_SETTINGS.get("provider") or "")[:80],
            "profile": str(_RUNTIME_SETTINGS.get("profile") or "")[:80],
            "model": str(_RUNTIME_SETTINGS.get("model") or "")[:160],
        }

    cooldowns: List[Dict[str, Any]] = []
    try:
        from models.providers.core.profiles import load_profile_store
        now = time.time()
        store = load_profile_store()
        for profile in store.list_profiles():
            remaining = max(0.0, float(getattr(profile, "cooldown_until", 0.0) or 0.0) - now)
            if remaining <= 0 and not getattr(profile, "cooldown_reason", ""):
                continue
            cooldowns.append({
                "provider": str(getattr(profile, "provider", ""))[:80],
                "profile": str(getattr(profile, "name", ""))[:80],
                "active": bool(getattr(profile, "active", True)),
                "enabled": bool(getattr(profile, "enabled", True)),
                "cooldown_seconds": round(remaining, 1),
                "reason": str(getattr(profile, "cooldown_reason", "") or "")[:64],
                "error_count": max(0, int(getattr(profile, "error_count", 0) or 0)),
            })
    except Exception:
        logger.debug("Provider cooldown diagnostics unavailable", exc_info=True)

    return {
        "active": selected,
        "attempts": attempts,
        "fallback_attempts": max(0, len(attempts) - 1),
        "cooldowns": cooldowns[:64],
        "last_failure": last_failure,
    }

def _lifecycle_persistence_health() -> Dict[str, Any]:
    """Project lifecycle durability health into the public health response."""
    try:
        from nexus.lifecycle.managers import get_component_supervisor

        stats = get_component_supervisor().get_stats()
        value = stats.get("persistence") if isinstance(stats, dict) else None
        if isinstance(value, dict):
            return {
                "available": bool(value.get("available", True)),
                "operation": str(value.get("operation", "none"))[:32],
                "error": str(value.get("error", ""))[:500],
                "updated_at": value.get("updated_at", 0.0),
            }
    except Exception as exc:
        logger.debug("Lifecycle persistence health unavailable", exc_info=True)
        return {"available": False, "operation": "health", "error": redact_secrets(exc)[:500], "updated_at": time.time()}
    return {"available": True, "operation": "none", "error": "", "updated_at": 0.0}


def _embed_queue_driver_enabled() -> bool:
    """Whether the server should run the embedded queue worker.

    Defaults to True: a server that accepts queued/cron work must have a
    worker, otherwise tasks accumulate forever. Set
    ``NEXUS_EMBED_QUEUE_DRIVER=false`` to run an external worker instead.
    """
    return os.environ.get("NEXUS_EMBED_QUEUE_DRIVER", "true").lower() in {
        "1", "true", "yes", "on",
    }


@app.get("/api/health")
def health():
    embedded = _embed_queue_driver_enabled()
    worker_running = bool(_QUEUE_DRIVER_TASK is not None and not _QUEUE_DRIVER_TASK.done())
    if embedded and not worker_running:
        # A server that advertises an embedded worker while that worker is
        # absent is not ready to receive unattended work.  Supervisors can
        # restart the process instead of routing tasks into a black hole.
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="embedded queue worker is not ready")
    return {
        "status": "ok",
        "service": "nexus-api",
        "queue_worker": "running" if worker_running else "external",
        "lifecycle_persistence": _lifecycle_persistence_health(),
    }


@app.get("/api/queue")
def queue_snapshot(session_id: str = "", include_global: bool = False, limit: int = 50):
    """Return a safe, bounded snapshot of the durable task queue.

    The TUI's ``/tasks`` view is intentionally backed by canonical session
    work-items.  This endpoint is the separate operator view for the SQLite
    queue that runs cron/autonomous work, so a client can distinguish queued
    work from an in-flight interactive turn without receiving lease tokens or
    raw payload metadata.
    """
    try:
        from queues.status import default_status_path, read_incident, read_status
        from queues.store import TaskQueue

        requested_session = safe_session_id(session_id) if session_id else ""
        bounded_limit = _work_item_limit(limit)
        queue = TaskQueue(root=_PROJECT_ROOT)
        states = queue.list_states(requested_session, include_global=include_global)
        rows = []
        for row in queue.list_unfinished():
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            task_session = str(meta.get("session_id") or "")
            if requested_session and task_session != requested_session:
                if not (include_global and not task_session):
                    continue
            description = redact_secrets(str(payload.get("task_desc") or "")).strip()
            rows.append({
                "id": int(row.get("id")),
                "state": str(row.get("state") or "unknown"),
                "summary": description[:240],
                "session_id": task_session,
                "priority": int(payload.get("priority") or 0),
                "attempts": int(row.get("attempts") or 0),
                "max_attempts": int(row.get("max_attempts") or 0),
                "created_at": float(row.get("created_at") or 0),
                "updated_at": float(row.get("updated_at") or 0),
                "leased_until": row.get("leased_until"),
"error": redact_secrets(str(row.get("error") or ""))[:500],
            })
            if len(rows) >= bounded_limit:
                break

        status_path = default_status_path(_PROJECT_ROOT)
        embedded = _embed_queue_driver_enabled()
        worker_running = bool(_QUEUE_DRIVER_TASK is not None and not _QUEUE_DRIVER_TASK.done())
        scope = "session+global" if requested_session and include_global else "session" if requested_session else "project"
        return {
            "status": "success",
            "scope": scope,
            "mode": "embedded" if embedded else "external",
            "worker": "running" if worker_running else "external" if not embedded else "stopped",
            "pending": queue.pending_count(requested_session, include_global=include_global),
            "states": states,
            "runtime": read_status(status_path),
            "incident": read_incident(_PROJECT_ROOT),
            "tasks": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Queue snapshot failed: %s", redact_secrets(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="Queue status unavailable") from exc


@app.get("/api/metrics")
def runtime_metrics():
    """Return bounded, restart-safe runtime metrics for operators."""
    from queues.status import default_status_path, read_incident, read_status

    status_path = default_status_path(_PROJECT_ROOT)
    queue_status = read_status(status_path)
    supervisor_incident = _read_optional_runtime_json(
        os.path.join(_PROJECT_ROOT, ".nexus", "supervisor_incident.json")
    )
    with _HIVES_LOCK:
        hive_statuses = [str(item.get("status") or "unknown").lower() for item in _HIVES.values()]
    embedded = _embed_queue_driver_enabled()
    return {
        "status": "success",
        "service": "nexus-api",
        "timestamp": time.time(),
        "queue": {
            "mode": "embedded" if embedded else "external",
            "worker_task": "running" if _QUEUE_DRIVER_TASK is not None and not _QUEUE_DRIVER_TASK.done() else "stopped",
            "runtime": queue_status,
            "incident": read_incident(_PROJECT_ROOT),
        },
        "supervisor": {"incident": supervisor_incident},
        "hives": {
            "total": len(hive_statuses),
            "running": sum(status == "running" for status in hive_statuses),
            "interrupted": sum(status == "interrupted" for status in hive_statuses),
            "failed": sum(status == "failed" for status in hive_statuses),
        },
    }


def _read_optional_runtime_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _prometheus_number(value: Any) -> str:
    return "1" if bool(value) else "0"


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    """Expose bounded Prometheus text metrics for standard supervisors."""
    payload = runtime_metrics()
    queue = payload.get("queue") or {}
    runtime = queue.get("runtime") or {}
    queue_incident = queue.get("incident") or {}
    supervisor_incident = (payload.get("supervisor") or {}).get("incident") or {}
    hives = payload.get("hives") or {}
    lines = [
        "# HELP nexus_up Nexus API process is serving metrics.",
        "# TYPE nexus_up gauge",
        "nexus_up 1",
        "# HELP nexus_queue_worker_running Embedded queue worker readiness.",
        "# TYPE nexus_queue_worker_running gauge",
        f"nexus_queue_worker_running {_prometheus_number(queue.get('worker_task') == 'running')}",
        "# HELP nexus_queue_runtime_healthy Queue runtime heartbeat is healthy.",
        "# TYPE nexus_queue_runtime_healthy gauge",
        f"nexus_queue_runtime_healthy {_prometheus_number(runtime.get('healthy'))}",
        "# HELP nexus_queue_quarantined Queue worker is quarantined.",
        "# TYPE nexus_queue_quarantined gauge",
        f"nexus_queue_quarantined {_prometheus_number(queue_incident.get('quarantined'))}",
        "# HELP nexus_supervisor_quarantined Outer supervisor is quarantined.",
        "# TYPE nexus_supervisor_quarantined gauge",
        f"nexus_supervisor_quarantined {_prometheus_number(supervisor_incident.get('state') == 'quarantined')}",
        "# HELP nexus_hives_total Known Hive count.",
        "# TYPE nexus_hives_total gauge",
        f"nexus_hives_total {int(hives.get('total', 0) or 0)}",
        "# HELP nexus_hives_running Running Hive count.",
        "# TYPE nexus_hives_running gauge",
        f"nexus_hives_running {int(hives.get('running', 0) or 0)}",
        "# HELP nexus_hives_interrupted Interrupted Hive count.",
        "# TYPE nexus_hives_interrupted gauge",
        f"nexus_hives_interrupted {int(hives.get('interrupted', 0) or 0)}",
        "# HELP nexus_hives_failed Failed Hive count.",
        "# TYPE nexus_hives_failed gauge",
        f"nexus_hives_failed {int(hives.get('failed', 0) or 0)}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


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
        # A timestamp-only id collides when the user creates two chats within
        # one second, which makes the second chat reopen the first on refresh.
        new_id = f"session_{uuid.uuid4().hex[:16]}"
        loop = get_loop(new_id)
        loop.save_memory()
        set_active_session(new_id, source="cli-api:new")
        return {"id": new_id, "title": "New Chat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Session creation", e))


def _command_load_session(session_id: str):
    """Session switch callback used by the shared slash-command registry."""
    sid = safe_session_id(session_id)
    loop = get_loop(sid)
    apply_runtime_settings(loop)
    set_active_session(sid, source="cli-api:command-session")
    return {"id": loop.session_id}


def _command_sync_permission_mode(mode: str) -> None:
    from security.policies.safety_store import sync_permission_from_legacy
    sync_permission_from_legacy(mode)


def _command_sync_sandbox_tier(tier: str) -> None:
    from security.policies.safety_store import sync_sandbox_from_legacy
    sync_sandbox_from_legacy(tier)


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
        raise HTTPException(status_code=500, detail=_public_api_failure("Session loading", e))


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    sid = safe_session_id(session_id)
    if sid == "default":
        if not _clear_session_files(sid):
            raise HTTPException(status_code=404, detail="Default session not found")
        return {"status": "success", "id": sid, "cleared": True}
    if not _delete_session_files(sid):
        return {"status": "error", "id": sid, "deleted": False}
    return {"status": "success", "id": sid, "deleted": True}


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
    """Persist session metadata atomically outside the async request loop."""
    directory = os.path.dirname(meta_path) or "."
    os.makedirs(directory, exist_ok=True)
    session_path = os.path.join(directory, f"{os.path.basename(meta_path)[:-5]}.json")
    with session_write_lock(session_path):
        atomic_write_json(meta_path, {"title": title})


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
    profile = chat_request.profile
    model = chat_request.model
    turn_id = chat_request.turn_id
    task_id = str(data.get("task_id") or "")
    max_tokens = chat_request.max_tokens
    requested_effort = str(data.get("reasoning_effort") or _RUNTIME_SETTINGS.get("effort") or "medium").strip().lower()
    if requested_effort == "extra_high":
        requested_effort = "xhigh"
    effort_tokens = {"minimal": 1024, "low": 2048, "medium": 4096, "high": 8192, "xhigh": 12288, "max": 16384, "ultra": 24576}
    if max_tokens is None and requested_effort in effort_tokens:
        max_tokens = effort_tokens[requested_effort]
    if requested_effort in effort_tokens:
        _RUNTIME_SETTINGS["effort"] = requested_effort
    conversation_history = chat_request.messages
    stream = bool(data.get("stream", False))
    canonical_events = bool(data.get("canonical_events", False))
    try:
        run_timeout = max(1.0, min(float(data.get("timeout_seconds") or os.environ.get("NEXUS_CHAT_TIMEOUT", "120")), 3600.0))
    except (TypeError, ValueError):
        run_timeout = 30.0

    try:
        nexus_loop = get_loop(sid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Session initialization", e))
    if bool(getattr(nexus_loop, "is_running", False)):
        raise HTTPException(status_code=409, detail="A run is already active for this session")

    # Reset any prior run state before starting a fresh turn (canonical
    # behaviour — the GUI client and tests rely on a clean loop per prompt).
    try:
        nexus_loop.reset()
    except Exception:
        logger.debug("get_loop reset failed for %s", sid, exc_info=True)

    set_active_session(sid, source="cli-api:chat")

    # Keep CLI/API runs on the same task/workflow contract as the GUI route.
    # Resume context is derived before execution, and completion is recorded
    # by the route-specific finally blocks below.
    resume_todo_context = ""
    try:
        resume_todo_context = await asyncio.to_thread(start_chat_workflow, sid, prompt, turn_id)
    except Exception:
        logger.debug("start_chat_workflow failed for %s", sid, exc_info=True)
    effective_prompt = build_resume_prompt(prompt, resume_todo_context)

    configured_provider, configured_model = configured_provider_defaults()
    requested_provider = provider if provider and provider != "auto" else configured_provider
    requested_model = model if model and model.lower() != "auto" else configured_model
    allowed_providers = {
        "openrouter", "qwen", "deepseek", "lm_studio", "anthropic", "openai",
        "gemini", "google_gemini", "groq", "ollama", "llama_cpp", "mistral",
        "cohere", "perplexity", "together", "huggingface", "sambanova",
        "fireworks", "xai", "commandcode", "nvidia"
    }
    safe_model = requested_model or getattr(nexus_loop, "model", "")
    if str(safe_model).lower() == "auto":
        safe_model = configured_model
    # The GUI persists the selected model independently from the provider.
    # Recover the provider from well-known model prefixes so a stale/early
    # model-picker state cannot silently route DeepSeek to LM Studio.
    model_provider = {
        "deepseek-chat": "deepseek",
        "deepseek-reasoner": "deepseek",
        "grok-": "grok",
        "nvidia/": "openrouter",
        "llama3": "ollama",
        "qwen3.5-": "lm_studio",
    }
    inferred_provider = next(
        (candidate for prefix, candidate in model_provider.items() if safe_model == prefix or safe_model.startswith(prefix)),
        None,
    )
    # A model-specific mapping wins over a stale/default provider value from
    # the client. The GUI historically sent `deepseek-chat` while the server
    # session still carried `lm_studio`, which caused valid cloud requests to
    # be sent to localhost:1234.
    safe_provider = inferred_provider or (requested_provider if requested_provider in allowed_providers else None)
    safe_profile = profile or getattr(nexus_loop, "profile_override", "") or None

    # Fail before entering the provider mesh when an explicitly selected cloud
    # provider has no usable credential. Otherwise the router can fall through
    # to an unrelated local provider and hide the actionable root cause.
    # Only perform provider readiness validation for a real Nexus loop.  This
    # keeps the transport contract usable for injected/test loop adapters,
    # while real loops still fail fast with an actionable configuration error.
    if safe_provider and safe_provider not in {"lm_studio", "ollama", "llama_cpp"} and hasattr(nexus_loop, "brain"):
        try:
            from models.providers.core.factory import NexusProviderFactory
            selected_provider = NexusProviderFactory().get_provider_by_name(
                "cloud", safe_provider, profile=safe_profile
            )
            if selected_provider is not None and not selected_provider.validate_api_key():
                key_name = f"{safe_provider.upper()}_API_KEY"
                raise HTTPException(
                    status_code=503,
                    detail=f"Provider '{safe_provider}' is not configured. Set {key_name} in the environment or configure it in Settings → Providers.",
                )
        except HTTPException:
            raise
        except Exception:
            logger.debug("Provider readiness check skipped for %s", safe_provider, exc_info=True)

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
        previous_sink = nexus_loop.work_event_sink
        stream_completed = False
        stream_succeeded = True
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=_WORK_EVENT_STREAM_QUEUE_SIZE)
        chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=_CHAT_CHUNK_QUEUE_SIZE)
        owner_loop = asyncio.get_running_loop()
        # Keep the generator handle outside ``pump_run`` so cancellation of
        # the SSE producer can explicitly close the underlying V5 stream.
        # Merely requesting an abort is cooperative; without aclose(), an
        # async generator blocked in a provider/tool await can retain the V5
        # run lock and make the next prompt look like a duplicate run.
        stream_gen = None

        def enqueue_event(event):
            # Persistence is authoritative. If a slow client fills the live
            # queue, drop the oldest live frame; reconnect/replay can recover
            # every persisted record without unbounded memory growth.
            try:
                event_queue.put_nowait(event)
            except asyncio.QueueFull:
                dropped = []
                while True:
                    try:
                        dropped.append(event_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                dropped_sequences = [
                    _safe_event_sequence(item)
                    for item in dropped
                    if isinstance(item, dict) and item.get("sequence")
                ]
                # Make overflow observable. The client can use this cursor
                # to request the durable replay endpoint instead of treating
                # a bounded-queue drop as a successful live stream.
                marker = {
                    "__stream_control__": "replay_required",
                    "after_sequence": max(0, min(dropped_sequences or [_safe_event_sequence(event, 1)]) - 1),
                }
                try:
                    event_queue.put_nowait(marker)
                    event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    return

        def stream_event_sink(payload):
            # Canonicalize and append under one cross-process critical section;
            # allocating a cursor before the append leaves a race window.
            event = append_work_event(sid, dict(payload))
            owner_loop.call_soon_threadsafe(enqueue_event, event)
            return event

        async def pump_run():
            nonlocal stream_succeeded, stream_gen
            response_parts: list[str] = []
            completed_normally = False
            run_succeeded = True
            failure_reason = ""
            try:
                run_kwargs = {
                    "provider": safe_provider,
                    "model": safe_model,
                    "max_tokens": max_tokens,
                    "turn_id": turn_id,
                    "conversation_history": conversation_history,
                }
                if safe_profile:
                    run_kwargs["profile"] = safe_profile
                if task_id:
                    run_kwargs["task_id"] = task_id
                run_kwargs["deadline_seconds"] = run_timeout

                def handle_chunk(chunk: dict) -> None:
                    nonlocal run_succeeded, stream_succeeded
                    if chunk.get("type") == "content":
                        response_parts.append(str(chunk.get("data") or ""))
                    if chunk.get("type") == "done" and isinstance(chunk.get("data"), dict):
                        run_succeeded = bool(chunk["data"].get("success", True))
                        stream_succeeded = run_succeeded
                    return chunk

                stream_gen = nexus_loop.stream_run(
                    effective_prompt,
                    **run_kwargs,
                )
                async with _chat_session_guard(sid):
                    if bool(getattr(nexus_loop, "is_running", False)):
                        await chunk_queue.put(("error", "A run is already active for this session"))
                        return
                    try:
                        first_chunk = await stream_gen.__anext__()
                    except StopAsyncIteration:
                        first_chunk = {"type": "done", "data": {"success": True}}
                handle_chunk(first_chunk)
                await chunk_queue.put(("chunk", first_chunk))
                async for chunk in stream_gen:
                    handle_chunk(chunk)
                    await chunk_queue.put(("chunk", chunk))
                completed_normally = True
            except asyncio.TimeoutError:
                run_succeeded = False
                stream_succeeded = False
                failure_reason = f"Response timed out after {run_timeout:.0f} seconds"
                await chunk_queue.put(("error", failure_reason))
            except asyncio.CancelledError:
                run_succeeded = False
                stream_succeeded = False
                failure_reason = "Response stream cancelled before completion"
                raise
            except Exception as exc:
                run_succeeded = False
                stream_succeeded = False
                failure_reason = str(exc)
                await chunk_queue.put(("error", str(exc)))
            finally:
                if stream_gen is not None:
                    try:
                        await stream_gen.aclose()
                    except Exception:
                        logger.debug("chat stream close failed for %s", turn_id, exc_info=True)
                if canonical_events and response_parts and (completed_normally or failure_reason):
                    stream_event_sink({
                        "event_id": f"message_{turn_id}",
                        "event_type": "message.completed" if completed_normally and run_succeeded else "message.failed",
                        "run_id": turn_id,
                        "turn_id": turn_id,
                        "kind": "message",
                        "title": "Assistant response completed" if completed_normally and run_succeeded else "Assistant response interrupted",
                        "status": "success" if completed_normally and run_succeeded else "failed",
                        "payload": {"content": "".join(response_parts)},
                        "error": failure_reason if not (completed_normally and run_succeeded) else "",
                        "visibility": "public",
                    })

        if canonical_events:
            nexus_loop.work_event_sink = stream_event_sink
        async def timed_pump():
            nonlocal stream_succeeded
            try:
                await asyncio.wait_for(pump_run(), timeout=run_timeout)
            except asyncio.TimeoutError:
                # ``wait_for`` cancels the inner generator before its local
                # exception state can reach the consumer. Propagate the
                # terminal failure explicitly so the route cannot persist a
                # timed-out stream as a successful run merely because the
                # producer emits its ordinary cleanup marker below.
                stream_succeeded = False
                request_abort = getattr(nexus_loop, "request_abort", None)
                if callable(request_abort):
                    request_abort(turn_id, "deadline_exceeded")
                await chunk_queue.put(("error", f"Response timed out after {run_timeout:.0f} seconds"))
            finally:
                await chunk_queue.put(("done", None))

        producer = asyncio.create_task(timed_pump())
        try:
            finished = False
            while not finished or not event_queue.empty():
                if not event_queue.empty():
                    event = event_queue.get_nowait()
                    if event.get("__stream_control__") == "replay_required":
                        yield "event: nexus.replay_required\ndata: " + json.dumps({"after_sequence": event["after_sequence"]}) + "\n\n"
                        continue
                    yield f"event: nexus.event\nid: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    continue

                event_wait = asyncio.create_task(event_queue.get()) if canonical_events else None
                chunk_wait = asyncio.create_task(chunk_queue.get())
                waits = {chunk_wait}
                if event_wait is not None:
                    waits.add(event_wait)
                completed, pending = await asyncio.wait(
                    waits,
                    timeout=_CHAT_HEARTBEAT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                if not completed:
                    yield ": nexus-heartbeat\n\n"
                    continue

                if event_wait is not None and event_wait in completed:
                    event = event_wait.result()
                    if event.get("__stream_control__") == "replay_required":
                        yield "event: nexus.replay_required\ndata: " + json.dumps({"after_sequence": event["after_sequence"]}) + "\n\n"
                    else:
                        yield f"event: nexus.event\nid: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if chunk_wait in completed:
                    kind, value = chunk_wait.result()
                    if kind == "done":
                        finished = True
                        stream_completed = True
                    elif kind == "error":
                        safe_err = str(value).replace('\n', ' ').replace('\r', '')
                        yield "event: error\n" + _sse_data(f"[NEXUS_SYSTEM_ERROR]: {safe_err}")
                    elif isinstance(value, dict) and value.get("type") == "content":
                        yield _sse_data(value['data'])
                    elif isinstance(value, dict) and value.get("type") == "done":
                        # Keep the existing terminal [DONE] protocol, but
                        # expose measured provider usage before it so clients
                        # can render a truthful context meter.
                        done_data = value.get("data")
                        usage = done_data.get("usage") if isinstance(done_data, dict) else None
                        if isinstance(usage, dict) and usage.get("source") == "provider":
                            yield "event: usage\n" + _sse_data(json.dumps(usage, ensure_ascii=False))
        except GeneratorExit:
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            safe_err = str(e).replace('\n', ' ').replace('\r', '')
            yield "event: error\n" + _sse_data(f"[NEXUS_SYSTEM_ERROR]: {safe_err}")
        finally:
            try:
                await asyncio.to_thread(
                    complete_chat_workflow,
                    sid,
                    prompt,
                    turn_id,
                    "done" if stream_completed and stream_succeeded else "failed",
                )
            except Exception:
                logger.debug("complete_chat_workflow failed for %s", sid, exc_info=True)
            if not stream_completed:
                request_abort = getattr(nexus_loop, "request_abort", None)
                if callable(request_abort):
                    try:
                        request_abort(turn_id, "client_disconnect")
                    except Exception:
                        logger.debug("chat disconnect abort failed for %s", sid, exc_info=True)
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            if canonical_events and nexus_loop.work_event_sink is stream_event_sink:
                nexus_loop.work_event_sink = previous_sink

    if stream:
        return StreamingResponse(async_generator(), media_type="text/event-stream")
    else:
        run_kwargs = {
            "provider": safe_provider,
            "model": safe_model,
            "max_tokens": max_tokens,
            "turn_id": turn_id,
            "conversation_history": conversation_history,
            "deadline_seconds": run_timeout,
        }
        if safe_profile:
            run_kwargs["profile"] = safe_profile
        if task_id:
            run_kwargs["task_id"] = task_id
        text = ""
        async with _chat_session_guard(sid):
            if bool(getattr(nexus_loop, "is_running", False)):
                text = "[NEXUS_SYSTEM_ERROR]: A run is already active for this session"
            else:
                gen = nexus_loop.stream_run(
                    effective_prompt,
                    **run_kwargs,
                )
                try:
                    text = await asyncio.wait_for(_collect_all(gen), timeout=run_timeout)
                except asyncio.TimeoutError:
                    request_abort = getattr(nexus_loop, "request_abort", None)
                    if callable(request_abort):
                        request_abort(turn_id, "deadline_exceeded")
                    if hasattr(gen, "aclose"):
                        await gen.aclose()
                    text = f"[NEXUS_SYSTEM_ERROR]: Response timed out after {run_timeout:.0f} seconds"
        try:
            await asyncio.to_thread(
                complete_chat_workflow,
                sid,
                prompt,
                turn_id,
                "failed" if text.startswith("[NEXUS_SYSTEM_ERROR]") else "done",
            )
        except Exception:
            logger.debug("complete_chat_workflow failed for %s", sid, exc_info=True)
        return {"response": text}


@app.post("/api/chat/{session_id}/cancel")
def cancel_chat(session_id: str, turn_id: str = ""):
    """Cancel the active run for a server-owned session."""
    sid = safe_session_id(session_id)
    nexus_loop = _LOOPS.get(sid)
    if nexus_loop is None:
        raise HTTPException(status_code=404, detail="Active session not found")
    run_id = str(turn_id or getattr(nexus_loop, "_current_turn_id", "") or "")
    if not run_id:
        raise HTTPException(status_code=409, detail="No active run id available")
    request_abort = getattr(nexus_loop, "request_abort", None)
    if callable(request_abort):
        if not request_abort(run_id):
            raise HTTPException(status_code=409, detail="Requested run is no longer active")
    else:
        try:
            nexus_loop.abort(turn_id=run_id)
        except TypeError:
            # Compatibility with legacy loop doubles and adapters whose
            # abort() method still accepts no keyword arguments.
            nexus_loop.abort()
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
        prov_path = os.path.join(_PROJECT_ROOT, "configure", "provider.yml")
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


@app.get("/models/saved")
@app.get("/api/models/saved")
async def list_saved_models():
    return await asyncio.to_thread(_list_saved_models_sync)


def _list_saved_models_sync():
    """Return provider-configured models in the shape used by the GUI picker.

    The GUI calls this endpoint during ``MainChat`` mount.  Keep this separate
    from the OpenAI-compatible ``/v1/models`` contract so the UI receives the
    provider and human-readable label it needs without reverse-engineering
    ``owned_by``.
    """
    models = []
    try:
        prov_path = os.path.join(_PROJECT_ROOT, "configure", "provider.yml")
        if os.path.isfile(prov_path) and yaml:
            with open(prov_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            providers = data.get("providers", {}) if isinstance(data, dict) else {}
            if isinstance(providers, dict):
                for provider, cfg in providers.items():
                    if not isinstance(cfg, dict) or not cfg.get("model"):
                        continue
                    model = str(cfg["model"])
                    alias = ""
                    try:
                        from models.providers.core.profiles import load_profile_store
                        for profile in load_profile_store().list_profiles(str(provider)):
                            native = str(getattr(profile, "model_id", "") or getattr(profile, "model", ""))
                            if native == model and getattr(profile, "active", True) and getattr(profile, "enabled", True):
                                alias = str(getattr(profile, "model_alias", "") or getattr(profile, "name", ""))
                                break
                    except Exception:
                        logger.debug("server: saved model aliases unavailable", exc_info=True)
                    models.append({
                        "model": model,
                        "provider": str(provider),
                        "profile": next((str(getattr(p, "name", "")) for p in load_profile_store().list_profiles(str(provider)) if str(getattr(p, "model_id", "") or getattr(p, "model", "")) == model and getattr(p, "active", True) and getattr(p, "enabled", True)), ""),
                        "alias": alias,
                        "label": alias or f"{provider}: {model}",
                    })
    except Exception:
        logger.warning("server: saved model listing failed", exc_info=True)
    return {"models": models}


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
        raise HTTPException(status_code=500, detail=_public_api_failure("OpenAI session initialization", e))

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
            yield f"data: {json.dumps({'error': _public_api_failure('OpenAI streaming', e)})}\n\n"

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
        raise HTTPException(status_code=500, detail=_public_api_failure("History retrieval", e))


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
def get_run_context(request: Request, session_id: str, run_id: str, include_events: bool = True, limit: int = 1000):
    """Return one durable run context plus collapsed or full public events."""
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
    explicit_full_events = request.query_params.get("include_events", "").lower() == "true"
    if explicit_full_events:
        safe_limit = _public_run_event_limit(limit)
        events = list_public_run_events(sid, resolved_run_id, limit=limit)
        response["events_mode"] = "complete"
        response["events_truncated"] = len(events) >= safe_limit
    elif include_events:
        events = list_work_events(sid, limit=limit, turn_id=resolved_run_id)
        response["events_mode"] = "collapsed"
    else:
        return response
    response["events"] = events
    response["next_sequence"] = max((_safe_event_sequence(event) for event in events), default=0)
    return response


def _public_work_item(item: Any) -> Dict[str, Any]:
    """Return a WorkItem without exposing server filesystem details."""
    payload = dict(item.to_dict())
    payload.pop("root", None)
    return payload


def _work_item_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit must be an integer") from exc
    if value < 1 or value > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    return value


def _active_work_item_plan(items: List[Any]) -> Optional[Dict[str, Any]]:
    """Project only the newest durable plan for TUI restart restoration.

    A session can retain work items from several superseded plans. Returning
    every item as one checklist makes old and new missions appear to be a
    single plan after reconnect. Plan creation time, rather than a later
    status update, selects the newest identity.
    """
    grouped: Dict[str, List[Any]] = {}
    for item in items:
        plan_id = str(getattr(item, "plan_id", "") or "").strip()
        if plan_id:
            grouped.setdefault(plan_id, []).append(item)
    if not grouped:
        return None
    plan_id, steps = max(
        grouped.items(),
        key=lambda pair: max(float(getattr(item, "created_at", 0.0) or 0.0) for item in pair[1]),
    )
    def step_order(item: Any) -> tuple:
        try:
            index = int((getattr(item, "metadata", {}) or {}).get("step_index", 10**9))
        except (TypeError, ValueError):
            index = 10**9
        return (
            index,
            float(getattr(item, "created_at", 0.0) or 0.0),
            str(getattr(item, "task_id", "") or ""),
        )

    ordered = sorted(
        steps,
        key=step_order,
    )
    return {
        "plan_id": plan_id,
        "steps": [_public_work_item(item) for item in ordered],
    }


@app.get("/api/work-items")
def list_work_items_api(session_id: str = "", limit: int = 100):
    """List durable WorkItems without changing the legacy /api/tasks contract."""
    sid = safe_session_id(session_id) if session_id else ""
    if sid:
        replay_work_item_event_log(
            root=_RUN_ROOT,
            session_id=sid,
            event_log_path=work_events_path(sid),
        )
    items = list_work_items(_RUN_ROOT, session_id=sid, limit=_work_item_limit(limit))
    return {
        "status": "success",
        "work_items": [_public_work_item(item) for item in items],
        "active_plan": _active_work_item_plan(items),
        "projection_failures": pending_work_item_projection_failures(
            event_log_path=work_events_path(sid)
        ),
    }


@app.get("/api/work-items/{session_id}/{task_id}")
def get_work_item_api(session_id: str, task_id: str):
    """Return one durable WorkItem, including its linked run identity when present."""
    sid = safe_session_id(session_id)
    replay_work_item_event_log(
        root=_RUN_ROOT,
        session_id=sid,
        event_log_path=work_events_path(sid),
    )
    item = load_work_item(_RUN_ROOT, sid, task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return {
        "status": "success",
        "work_item": _public_work_item(item),
        "projection_failures": pending_work_item_projection_failures(
            event_log_path=work_events_path(sid)
        ),
    }


@app.get("/api/work-events")
def get_work_events(request: Request, session_id: str = "default", limit: int = 200, turn_id: str = "", after_sequence: int = 0):
    header_cursor = request.headers.get("Last-Event-ID", "").strip()
    if header_cursor:
        try:
            after_sequence = max(after_sequence, int(header_cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer sequence")
    raw_events = _session_work_events(session_id)
    retained_sequences = [_safe_event_sequence(event) for event in raw_events if _safe_event_sequence(event) > 0]
    oldest_sequence = min(retained_sequences, default=0)
    replay_truncated = bool(after_sequence and oldest_sequence and after_sequence < oldest_sequence - 1)
    # Cursor clients need every transition after their checkpoint. The normal
    # read remains lifecycle-collapsed for the GUI timeline.
    if after_sequence:
        events = replay_work_events_after(session_id, after_sequence, limit=limit)
        if turn_id:
            events = [event for event in events if str(event.get("turn_id") or event.get("run_id") or "") == str(turn_id)]
    else:
        events = list_work_events(session_id, limit=limit, turn_id=turn_id, after_sequence=after_sequence)
    next_sequence = max((_safe_event_sequence(event) for event in events), default=after_sequence)
    replay_gap = {
        "detected": replay_truncated,
        "after_sequence": after_sequence,
        "oldest_sequence": oldest_sequence,
        "missing_until": max(0, oldest_sequence - 1) if replay_truncated else 0,
    }
    return {
        "events": events,
        "after_sequence": after_sequence,
        "next_sequence": next_sequence,
        "oldest_sequence": oldest_sequence,
        "replay_truncated": replay_truncated,
        "replay_gap": replay_gap,
    }


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
    try:
        timeout = max(5, min(int(data.get("timeout", 90)), 180))
    except (TypeError, ValueError):
        timeout = 90

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
            stream_kwargs = {"timeout": timeout}
            if profile == "pwsh":
                stream_kwargs["shell"] = "powershell"
            elif profile == "cmd":
                stream_kwargs["shell"] = "cmd"
            elif profile == "bash":
                stream_kwargs["shell"] = "bash"
            elif profile == "wsl":
                stream_kwargs["shell"] = "wsl"
            async for text in sandbox.stream_execute(command, _PROJECT_ROOT, **stream_kwargs):
                output_parts.append(text)
                yield sse({"type": "chunk", "stream": "stderr" if text.startswith("[SANDBOX_") else "stdout", "text": text})
            output = "".join(output_parts)
            exit_code = sandbox.last_exit_code if sandbox.last_exit_code is not None else 0
            status = "success" if exit_code == 0 else "failed"
            stderr = output if status == "failed" else ""
            completed = _append_work_event(sid, {
                **started, "id": started.get("id"), "event_id": started.get("event_id"), "status": status,
                "stdout": output, "stderr": stderr, "output": output,
                "exit_code": exit_code, "completed_at": time.time(),
            })
            yield sse({"type": "done", "status": status, "event": completed, "output": output, "stderr": stderr, "exit_code": exit_code})
        except Exception as exc:
            message = str(exc)
            completed = _append_work_event(sid, {
                **started, "id": started.get("id"), "event_id": started.get("event_id"), "status": "failed",
                "stdout": "", "stderr": message, "output": message,
                "completed_at": time.time(),
            })
            yield sse({"type": "chunk", "stream": "stderr", "text": message})
            yield sse({"type": "done", "status": "failed", "event": completed, "output": message, "stderr": message})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── New CLI Backend Endpoints ────────────────────────────────────────────────

_TASKS: Dict[str, dict] = _load_tasks()
try:
    _TASK_COUNTER = max([int(k.split("_")[1]) for k in _TASKS if "_" in k] or [0])
except (ValueError, IndexError, TypeError):
    # A hand-edited tasks.json may contain non-numeric task ids; the server
    # must still start, the next counter simply starts from zero.
    _TASK_COUNTER = 0


@app.get("/api/skills")
def list_skills():
    """List the same active skills exposed to the model-facing registry."""
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
    # Keep the dashboard/API view aligned with the exact discovery source used
    # by the direct model/tool loop.  This includes legacy and bundled skills,
    # not only config entries and .opencode/skills folders.
    try:
        from extensions.tools.built_in.nexus_tools.registry import ToolRegistry

        registry = ToolRegistry(_PROJECT_ROOT)
        for name, entry in registry._tools.items():
            if (entry.schema or {}).get("category") != "skill":
                continue
            availability = entry.availability()
            by_name[name] = {
                "name": name,
                "description": str((entry.schema or {}).get("description", "NEXUS skill")),
                "enabled": bool(availability.get("available", False)),
            }
    except Exception:
        logger.warning("server: list_skills registry discovery failed", exc_info=True)
    return {"skills": sorted(by_name.values(), key=lambda item: item["name"])}


@app.get("/api/tools")
def list_tools():
    """List registered tools from ToolRegistry."""
    summary = _config_summary()
    config_tools = {tool["name"]: tool for tool in summary["tools"]}
    try:
        from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
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
        return {
            "tools": list(config_tools.values()),
            "error": _public_api_failure("Tool inventory", e),
        }


@app.post("/api/verification/run")
async def run_programmatic_verification(request: Request):
    """Run an explicit, sandboxed verification recipe and return durable facts."""
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Verification request must be an object")
    auto_recipe = str(data.get("recipe") or "").strip().lower() == "auto"
    commands = data.get("commands")
    if not auto_recipe and (not isinstance(commands, list) or not commands or len(commands) > 32):
        raise HTTPException(status_code=400, detail="commands must be a non-empty list of at most 32 items")
    for check in commands or []:
        if isinstance(check, str):
            if not check.strip():
                raise HTTPException(status_code=400, detail="commands must contain non-empty strings")
        elif isinstance(check, dict):
            if not isinstance(check.get("command"), str) or not check["command"].strip():
                raise HTTPException(status_code=400, detail="verification checks require a non-empty command")
            if check.get("phase") is not None and not isinstance(check.get("phase"), str):
                raise HTTPException(status_code=400, detail="verification phase must be a string")
        else:
            raise HTTPException(status_code=400, detail="commands must contain strings or check objects")
    raw_root = str(data.get("root") or _PROJECT_ROOT).strip()
    target = Path(raw_root).expanduser()
    if not target.is_absolute():
        target = Path(_PROJECT_ROOT) / target
    try:
        target = target.resolve(strict=False)
        project_root = Path(_PROJECT_ROOT).resolve(strict=False)
        target.relative_to(project_root)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=403, detail="verification root must be inside the Nexus workspace")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="verification root is not a directory")
    try:
        timeout = max(1.0, min(float(data.get("timeout", 600.0)), 3600.0))
        total_timeout = max(1.0, min(float(data.get("total_timeout", timeout)), 3600.0))
        readiness_timeout = max(0.1, min(float(data.get("readiness_timeout", 10.0)), 60.0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="timeouts must be numeric and within their allowed bounds")
    from nexus.main_agent.programmatic_verify import (
        run_detected_verification, run_programmatic_verification as run_verify,
    )

    if auto_recipe:
        result = await run_detected_verification(
            target, session_id=str(data.get("session_id") or "default"),
            timeout=timeout, total_timeout=total_timeout,
            stop_on_failure=bool(data.get("stop_on_failure", True)),
        )
    else:
        result = await run_verify(
            target, commands, session_id=str(data.get("session_id") or "default"),
            timeout=timeout, total_timeout=total_timeout,
            readiness_url=data.get("readiness_url"), readiness_timeout=readiness_timeout,
            stop_on_failure=bool(data.get("stop_on_failure", True)),
        )
    return result.to_dict()


@app.get("/api/verification/recipe")
def get_verification_recipe(root: str = ""):
    """Detect a read-only verification recipe for a workspace path."""
    target = Path(root or _PROJECT_ROOT).expanduser()
    if not target.is_absolute():
        target = Path(_PROJECT_ROOT) / target
    try:
        target = target.resolve(strict=False)
        target.relative_to(Path(_PROJECT_ROOT).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=403, detail="recipe root must be inside the Nexus workspace")
    from nexus.main_agent.verification_recipes import detect_verification_recipe

    recipe = detect_verification_recipe(target)
    return {"recipe": recipe.to_dict() if recipe else None, "root": str(target)}


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
        from models.providers.core.profiles import load_profile_store
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
    """List MCP servers from settings.yml."""
    return {"mcp": _config_summary()["mcp"]}


@app.post("/api/mcp")
async def create_mcp(request: Request):
    """Create or replace an MCP server from the Settings UI."""
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="MCP configuration must be an object")
    name = str(body.get("name") or "").strip()
    command = str(body.get("command") or body.get("cmd") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="MCP server name is required")
    if not command:
        raise HTTPException(status_code=400, detail="MCP server command is required")
    args = body.get("args", [])
    if isinstance(args, str):
        args = [part.strip() for part in args.splitlines() if part.strip()]
    if not isinstance(args, list):
        raise HTTPException(status_code=400, detail="MCP args must be a list or newline-separated string")
    entry = {
        "command": command,
        "args": [str(part) for part in args],
        "description": str(body.get("description") or "").strip(),
        "active": bool(body.get("active", True)),
    }
    for field in ("env", "working_dir"):
        if body.get(field) is not None:
            entry[field] = body[field]
    await asyncio.to_thread(_create_mcp_config_sync, name, entry)
    _clear_runtime("mcp config changed")
    return {"status": "success", "id": name, "mcp": entry}


@app.delete("/api/mcp/{name}")
def delete_mcp(name: str):
    """Remove an MCP server from both configuration stores."""
    config = _load_nexus_config()
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict) or name not in servers:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    servers.pop(name, None)
    _save_nexus_config(config)
    _sync_mcp_servers_file(config)
    _clear_runtime("mcp config changed")
    return {"status": "success", "id": name}


@app.get("/api/hives")
def list_hives():
    """List hive status and active hives."""
    hive = None
    engine_error = ""
    personas: List[str] = []
    try:
        hive = _get_hive_engine()
        personas = list(hive.list_personas().keys())
    except Exception as exc:
        # Never fabricate personas when the engine is unavailable: the client
        # must see the engine is down, not a fake WORKER roster (audit P36).
        engine_error = str(exc)[:400]
        logger.warning("server: list_hives: hive engine unavailable: %s", engine_error, exc_info=True)

    with _HIVES_LOCK:
        hives_list = []
        for hive_id, hive_data in _HIVES.items():
            agents = hive_data.get("agents", [])
            engine_agents = []
            if hive is not None:
                engine_agents = [hive.get_agent(item.get("id", "")) for item in agents]
            for item, live in zip(agents, engine_agents):
                if live is not None:
                    item["status"] = live.status
            statuses = {str(item.get("status") or "").lower() for item in agents}
            partial = bool(
                "success" in statuses
                and statuses.intersection({"failed", "cancelled", "canceled", "error"})
            )
            hive_data["partial"] = partial
            terminal = {"success", "failed", "cancelled", "canceled", "error"}
            if statuses and statuses.issubset(terminal):
                if statuses == {"success"}:
                    hive_data["status"] = "success"
                elif statuses.issubset({"cancelled", "canceled"}):
                    hive_data["status"] = "cancelled"
                else:
                    hive_data["status"] = "failed"
            hives_list.append({
                "id": hive_id,
                "status": hive_data.get("status", "unknown"),
                "partial": partial,
                "agents": agents,
                "result": hive_data.get("result", ""),
                "consolidation_error": hive_data.get("consolidation_error", ""),
            })
    _persist_hive_manifest()

    features = _runtime_features(_load_nexus_config())
    enabled = features.get("hive", True)

    return {
        "enabled": enabled,
        "personas": personas,
        "hives": hives_list,
        "engine": {
            "available": not bool(engine_error),
            "error": redact_secrets(engine_error) if engine_error else "",
        },
    }


@app.post("/api/hives")
async def create_hive(request: Request):
    """Create a new hive with multiple sub-agents."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    agents_input = body.get("agents", [])
    if not isinstance(agents_input, list):
        raise HTTPException(status_code=400, detail="agents must be a list")

    if not agents_input:
        raise HTTPException(status_code=400, detail="agents list cannot be empty")

    # Validate each agent entry
    for agent in agents_input:
        if not isinstance(agent, dict):
            raise HTTPException(status_code=400, detail="each agent must be a dict")
        if "task" not in agent or not isinstance(agent["task"], str):
            raise HTTPException(status_code=400, detail="each agent must have a 'task' string")
        if "persona" not in agent or not isinstance(agent["persona"], str):
            raise HTTPException(status_code=400, detail="each agent must have a 'persona' string")

    try:
        hive_engine = _get_hive_engine()
        tasks = [(agent["task"], agent["persona"]) for agent in agents_input]
        hive_id, spawned = await hive_engine.spawn_hive(tasks)
    except Exception as e:
        logger.warning(f"Hive engine spawn failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Hive could not start: {e}")

    agent_summaries = [
        {
            "id": agent.agent_id,
            "task": agent.task,
            "persona": agent.persona,
            "status": agent.status,
        }
        for agent in spawned
    ]
    terminal_statuses = {"success", "failed", "cancelled", "canceled", "error"}
    observed_statuses = {str(agent.get("status") or "").lower() for agent in agent_summaries}
    hive_status = "running"
    if observed_statuses and observed_statuses.issubset(terminal_statuses):
        hive_status = "success" if observed_statuses == {"success"} else (
            "cancelled" if observed_statuses.issubset({"cancelled", "canceled"}) else "failed"
        )

    with _HIVES_LOCK:
        _HIVES[hive_id] = {
            "id": hive_id,
            "status": hive_status,
            "agents": agent_summaries,
            "created_at": time.time(),
            "result": "",
            "consolidation_error": "",
        }
    _persist_hive_manifest()

    # Collect the consolidated result in the background so callers can poll
    # GET /api/hives for the final answer instead of losing it.
    task = asyncio.create_task(_consolidate_api_hive(hive_id, hive_engine))
    _HIVE_CONSOLIDATION_TASKS.add(task)
    task.add_done_callback(_HIVE_CONSOLIDATION_TASKS.discard)

    return {
        "status": "success",
        "hive": {
            "id": hive_id,
            "status": hive_status,
            "agents": _HIVES[hive_id]["agents"]
        }
    }


@app.post("/api/hives/{hive_id}/cancel")
async def cancel_hive(hive_id: str):
    """Cancel a running hive."""
    with _HIVES_LOCK:
        if hive_id not in _HIVES:
            raise HTTPException(status_code=404, detail=f"Hive {hive_id} not found")

    try:
        hive_engine = _get_hive_engine()
        await hive_engine.cancel_hive(hive_id)
    except Exception as e:
        logger.warning(f"Hive {hive_id} cancel engine call failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel hive {hive_id}: {e}")

    with _HIVES_LOCK:
        # Mark as cancelled
        _HIVES[hive_id]["status"] = "cancelled"
        for agent in _HIVES[hive_id]["agents"]:
            if str(agent.get("status") or "").lower() not in {"success", "failed", "error"}:
                agent["status"] = "cancelled"
    _persist_hive_manifest()

    return {"status": "success"}


@app.post("/api/hives/{hive_id}/pause")
async def pause_hive(hive_id: str):
    """Pause a running Hive at the next safe model/tool boundary."""
    with _HIVES_LOCK:
        summary = _HIVES.get(hive_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Hive {hive_id} not found")
        if str(summary.get("status") or "").lower() != "running":
            raise HTTPException(status_code=409, detail="Hive is not running")
    try:
        await _get_hive_engine().pause_hive(hive_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with _HIVES_LOCK:
        _HIVES[hive_id]["status"] = "paused"
        _HIVES[hive_id]["paused_at"] = time.time()
    _persist_hive_manifest()
    return {"status": "success", "hive": _HIVES[hive_id]}


@app.post("/api/hives/{hive_id}/resume")
async def resume_hive(hive_id: str):
    """Resume a paused Hive in place or re-spawn interrupted work after restart."""
    with _HIVES_LOCK:
        previous = _HIVES.get(hive_id)
        if previous is None:
            raise HTTPException(status_code=404, detail=f"Hive {hive_id} not found")
        if previous.get("status") == "running":
            raise HTTPException(status_code=409, detail="Hive is already running")
        resumable_agents = [
            agent for agent in previous.get("agents", [])
            if isinstance(agent, dict)
            and str(agent.get("task") or "").strip()
            and str(agent.get("status") or "pending").lower() in {"pending", "running", "paused", "interrupted"}
        ]
        tasks = [
            (str(agent.get("task") or ""), str(agent.get("persona") or "WORKER"))
            for agent in resumable_agents
        ]
        agent_ids = [str(agent.get("id") or "") for agent in resumable_agents]
        paused_in_place = str(_HIVES[hive_id].get("status") or "").lower() == "paused"
        engine = _get_hive_engine() if paused_in_place else None
        paused_in_place = paused_in_place and hive_id in getattr(engine, "_hives", {})
    if paused_in_place:
        try:
            await engine.resume_hive(hive_id)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        with _HIVES_LOCK:
            _HIVES[hive_id]["status"] = "running"
            _HIVES[hive_id].pop("paused_at", None)
        _persist_hive_manifest()
        return {"status": "success", "hive": _HIVES[hive_id]}
    if not tasks:
        raise HTTPException(status_code=400, detail="Hive has no resumable tasks")

    try:
        hive_engine = _get_hive_engine()
        # Keep resume compatible with lightweight engine doubles and older
        # integrations while using stable IDs whenever the engine supports
        # checkpoint hydration.  Do not catch arbitrary TypeError from inside
        # spawn_hive: a real implementation error must remain visible.
        spawn_hive = hive_engine.spawn_hive
        try:
            spawn_parameters = inspect.signature(spawn_hive).parameters
        except (TypeError, ValueError):
            spawn_parameters = {}
        accepts_agent_ids = (
            "agent_ids" in spawn_parameters
            or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in spawn_parameters.values()
            )
        )
        if accepts_agent_ids:
            new_id, spawned = await spawn_hive(
                tasks, parent_run_id=hive_id, agent_ids=agent_ids
            )
        else:
            new_id, spawned = await spawn_hive(tasks, parent_run_id=hive_id)
    except Exception as e:
        logger.warning("Hive %s resume failed: %s", hive_id, e, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Hive could not resume: {e}")

    with _HIVES_LOCK:
        previous["resumed_to"] = new_id
        previous["status"] = "superseded"
        _HIVES[new_id] = {
            "id": new_id,
            "status": "running",
            "resumed_from": hive_id,
            "agents": [
                {"id": agent.agent_id, "task": agent.task, "persona": agent.persona, "status": agent.status}
                for agent in spawned
            ],
            "created_at": time.time(),
        }
    _persist_hive_manifest()
    return {
        "status": "success",
        "hive": _HIVES[new_id],
    }


# ---------------------------------------------------------------------------
# Nexus Hive capability boundary (main-agent <-> Hive)
#
# The Nexus MAIN AGENT is OUTSIDE Hive.  These endpoints expose the clean
# HiveCapability boundary: submit a goal, list/inspect runs, and manage
# reusable Agent Teams.  They sit alongside the lower-level /api/hives
# sub-agent spawner and DO NOT place the main agent inside Hive.
# ---------------------------------------------------------------------------

_HIVE_CAPABILITY = None


def _get_hive_capability():
    global _HIVE_CAPABILITY
    if _HIVE_CAPABILITY is not None:
        return _HIVE_CAPABILITY
    from hive.capability import HiveCapability
    from hive import DEFAULT_AVAILABLE_CAPABILITIES
    engine = _get_hive_engine()
    root = str(getattr(engine, "root", ".") or ".")
    tool_registry = getattr(engine, "tool_registry", None)
    _HIVE_CAPABILITY = HiveCapability(
        root or ".",
        engine=engine,
        tool_registry=tool_registry,
        available_capabilities=dict(DEFAULT_AVAILABLE_CAPABILITIES),
        sink=None,
    )
    return _HIVE_CAPABILITY


@app.post("/api/hive/goal")
async def hive_submit_goal(request: Request):
    """Hand a goal/task/long-running responsibility to Hive (S3)."""
    try:
        from hive import HiveRequest, CapabilityMode, ConnectionMode
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        req = HiveRequest(
            goal=str(body.get("goal") or body.get("task") or ""),
            task=str(body.get("task") or ""),
            expected_outcome=str(body.get("expected_outcome") or ""),
            completion_criteria=list(body.get("completion_criteria") or []),
            priority=int(body.get("priority", 5)),
            team_preference=str(body.get("team_preference") or "") or None,
            required_specializations=list(body.get("required_specializations") or []),
            required_tools=list(body.get("required_tools") or []),
            required_skills=list(body.get("required_skills") or []),
            required_plugins=list(body.get("required_plugins") or []),
            required_mcp_servers=list(body.get("required_mcp_servers") or []),
            provider_preference=str(body.get("provider_preference") or "") or None,
            model_preference=str(body.get("model_preference") or "") or None,
            token_budget=int(body["token_budget"]) if body.get("token_budget") else None,
            cost_budget=float(body["cost_budget"]) if body.get("cost_budget") else None,
            runtime_budget_seconds=float(body["runtime_budget_seconds"]) if body.get("runtime_budget_seconds") else None,
            max_agents=int(body["max_agents"]) if body.get("max_agents") else None,
            max_parallel_agents=int(body["max_parallel_agents"]) if body.get("max_parallel_agents") else None,
            allow_continuous=bool(body.get("allow_continuous", False)),
            require_human_approval=bool(body.get("require_human_approval", False)),
            final_output_format=str(body.get("final_output_format") or "text"),
            capability_mode=str(body.get("capability_mode") or CapabilityMode.ROLE_BASED.value),
            connection_mode=str(body.get("connection_mode") or ConnectionMode.INHERIT.value),
        )
        cap = _get_hive_capability()
        if body.get("execute", False):
            summary = await cap.plan_and_execute(req)
        else:
            summary = await cap.submit_goal(req)
        return {"status": "success", "run": summary.to_dict()}
    except Exception as e:
        import logging as _log
        _log.warning("Hive goal submission failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Hive goal rejected: {e}")


@app.get("/api/hive/runs")
async def hive_list_runs():
    """List Hive runs created via the capability boundary."""
    try:
        cap = _get_hive_capability()
        runs = []
        for rid in cap.list_runs(limit=100):
            try:
                runs.append((await cap.get_run(rid)).to_dict())
            except Exception:
                runs.append({"hive_run_id": rid, "status": "unknown"})
        return {"status": "success", "runs": runs, "count": len(runs)}
    except Exception as e:
        import logging as _log
        _log.warning("Hive list runs failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Hive list failed: {e}")


@app.post("/api/hive/runs/{run_id}/continuous")
async def hive_run_continuous(run_id: str):
    """Run a Hive run as a controlled long-running / 24/7 loop (§17, §19)."""
    try:
        cap = _get_hive_capability()
        summary = await cap.run_continuous(run_id)
        return {"status": "success", "run": summary.to_dict()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Hive run {run_id} not found")
    except Exception as e:
        import logging as _log
        _log.warning("Hive continuous run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Hive continuous run failed: {e}")


@app.post("/api/hive/runs/{run_id}/cancel")
async def hive_cancel_run(run_id: str):
    """Cancel a Hive run (operator control)."""
    try:
        cap = _get_hive_capability()
        await cap.cancel(run_id)
        return {"status": "success", "hive_run_id": run_id}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Hive run {run_id} not found")
    except Exception as e:
        import logging as _log
        _log.warning("Hive cancel failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Hive cancel failed: {e}")


@app.get("/api/hive/teams")
async def hive_list_teams():
    """List reusable Agent Team templates (plug-and-play)."""
    try:
        from hive import list_team_templates
        teams = [t.to_dict() for t in list_team_templates()]
        return {"status": "success", "teams": teams, "count": len(teams)}
    except Exception as e:
        import logging as _log
        _log.warning("Hive list teams failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Hive teams failed: {e}")


@app.get("/api/gateways")
def list_gateways():
    """List available gateway platforms and their status."""
    try:
        from gateways.platforms import all_adapters
        from gateways.run import _PLATFORM_ENV_MAP, _has_required_env
    except Exception:
        logger.warning("server: list_gateways: gateway module not available", exc_info=True)
        return {"gateways": []}

    gateways = []
    for platform in all_adapters():
        required = _PLATFORM_ENV_MAP.get(platform, [])
        has_env = _has_required_env(required)
        gateways.append({
            "id": platform,
            "name": platform.replace("_", " ").title(),
            "status": "idle",
            "enabled": has_env,
            "description": f"NEXUS {platform.replace('_', ' ')} gateway"
        })

    return {"gateways": gateways}


@app.get("/api/cron/jobs")
def list_cron_jobs():
    """List durable cron definitions and their next execution time."""
    jobs = _get_cron_queue().list_cron_jobs()
    for job in jobs:
        job["description"] = f"Interval: {job.get('interval_minutes', 0)} minutes"
    return {"jobs": jobs, "status": "ok"}


@app.post("/api/cron/jobs")
async def create_cron_job(request: Request):
    """Create a new cron job."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = body.get("name")
    prompt = body.get("prompt")
    interval_minutes = body.get("interval_minutes")
    enabled = body.get("enabled", True)

    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="name is required")
    if not prompt or not isinstance(prompt, str):
        raise HTTPException(status_code=400, detail="prompt is required")
    if not isinstance(interval_minutes, int) or interval_minutes <= 0:
        raise HTTPException(status_code=400, detail="interval_minutes must be a positive integer")

    job_id = f"cron_{uuid.uuid4().hex[:8]}"
    job = _get_cron_queue().create_cron_job(
        job_id, name, prompt, interval_minutes, enabled=bool(enabled), next_run_at=time.time()
    )
    return {"status": "success", "job": job}


# ── Voice API endpoints ────────────────────────────────────────────────────────

_VOICE_ASSISTANT: Dict[str, Any] = {}
_VOICE_LOCK = threading.Lock()


def _get_voice_assistant(session_id: str = "default"):
    """Get or create a VoiceAssistant instance for a session."""
    with _VOICE_LOCK:
        if session_id not in _VOICE_ASSISTANT:
            try:
                from apps.voice.pipeline import VoiceAssistant
                _VOICE_ASSISTANT[session_id] = VoiceAssistant(session_id=session_id)
                _VOICE_ASSISTANT[session_id].warmup()
            except Exception as e:
                logger.error("Failed to create VoiceAssistant: %s", redact_secrets(e), exc_info=True)
                raise HTTPException(status_code=500, detail="Voice system unavailable") from e
        return _VOICE_ASSISTANT[session_id]


def _voice_failure(operation: str, exc: Exception) -> str:
    """Log a diagnostic safely and return a stable public voice error."""
    logger.error("Voice %s failed: %s", operation, redact_secrets(exc), exc_info=True)
    return f"Voice {operation} unavailable"


def _persist_voice_settings(values: Dict[str, Any]) -> None:
    """Persist only supported voice settings through the serialized config API."""
    from configure.config_loader import NexusConfigLoader

    loader = NexusConfigLoader()
    current = loader.get("voice", {})
    voice_config = dict(current) if isinstance(current, dict) else {}
    for key in ("auto_speak", "voice_name", "whisper_language", "volume", "speech_speed"):
        if key in values:
            voice_config[key] = values[key]
    loader.set("voice", voice_config)
    loader.save()


@app.get("/api/voice/status")
def voice_status(session_id: str = "default"):
    """Get voice system status and settings."""
    try:
        assistant = _get_voice_assistant(session_id)
        return {
            "status": "ok",
            "enabled": assistant.settings.enabled,
            "auto_speak": assistant.settings.auto_speak,
            "continuous_listening": assistant.settings.continuous_listening,
            "voice_name": assistant.settings.voice_name,
            "whisper_language": assistant.settings.whisper_language,
            "statistics": assistant.get_voice_statistics()
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": _voice_failure("status", e)}


@app.post("/api/voice/listen/start")
async def voice_listen_start(request: Request):
    """Start voice listening (continuous mode)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    session_id = body.get("session_id", "default")
    continuous = body.get("continuous", True)
    
    try:
        assistant = _get_voice_assistant(session_id)
        if continuous:
            assistant.start_continuous_listening()
        return {"status": "ok", "listening": True, "continuous": continuous}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("listening start", e)) from e


@app.post("/api/voice/listen/stop")
def voice_listen_stop(session_id: str = "default"):
    """Stop voice listening."""
    try:
        assistant = _get_voice_assistant(session_id)
        assistant.stop_continuous_listening()
        return {"status": "ok", "listening": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("listening stop", e)) from e


@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """Transcribe audio data."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    session_id = body.get("session_id", "default")
    continuous = body.get("continuous", False)
    
    try:
        assistant = _get_voice_assistant(session_id)
        text = assistant.listen_once(continuous=continuous)
        return {"status": "ok", "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("transcription", e)) from e


@app.post("/api/voice/speak")
async def voice_speak(request: Request):
    """Convert text to speech."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    session_id = body.get("session_id", "default")
    text = body.get("text", "")
    blocking = body.get("blocking", False)
    
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    
    try:
        assistant = _get_voice_assistant(session_id)
        success = assistant.speak(text, blocking=blocking)
        return {"status": "ok", "spoken": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("speech", e)) from e


@app.post("/api/voice/speak/stop")
def voice_speak_stop(session_id: str = "default"):
    """Stop current speech."""
    try:
        assistant = _get_voice_assistant(session_id)
        assistant.stop_speaking()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("speech stop", e)) from e


@app.get("/api/voice/voices")
def voice_voices():
    """List available TTS voices."""
    try:
        from apps.voice.pipeline import VoiceAssistant
        return {"status": "ok", "voices": VoiceAssistant.get_available_voices(None)}
    except Exception as e:
        return {"status": "error", "message": _voice_failure("voice listing", e), "voices": []}


@app.get("/api/voice/languages")
def voice_languages():
    """List supported STT languages."""
    try:
        from apps.voice.pipeline import VoiceAssistant
        return {"status": "ok", "languages": VoiceAssistant.get_available_languages(None)}
    except Exception as e:
        return {"status": "error", "message": _voice_failure("language listing", e), "languages": []}


@app.get("/api/voice/history")
def voice_history(session_id: str = "default", limit: int = 10):
    """Get transcription history."""
    try:
        assistant = _get_voice_assistant(session_id)
        history = assistant.get_transcription_history(limit)
        return {"status": "ok", "history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("history", e)) from e


@app.post("/api/voice/settings")
async def voice_settings(request: Request):
    """Update voice settings."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    session_id = body.get("session_id", "default")
    
    try:
        assistant = _get_voice_assistant(session_id)
        # Update settings that can be changed dynamically
        if "auto_speak" in body:
            assistant.settings.auto_speak = body["auto_speak"]
        if "voice_name" in body:
            assistant.settings.voice_name = body["voice_name"]
        if "whisper_language" in body:
            assistant.settings.whisper_language = body["whisper_language"]
        if "volume" in body:
            assistant.settings.volume = body["volume"]
        if "speech_speed" in body:
            assistant.settings.speech_speed = body["speech_speed"]

        await asyncio.to_thread(_persist_voice_settings, body)
        
        return {"status": "ok", "settings": {
            "auto_speak": assistant.settings.auto_speak,
            "voice_name": assistant.settings.voice_name,
            "whisper_language": assistant.settings.whisper_language,
            "volume": assistant.settings.volume,
            "speech_speed": assistant.settings.speech_speed,
        }}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_voice_failure("settings update", e)) from e


@app.get("/api/voice/stream")
async def voice_stream(request: Request):
    """Stream voice transcriptions and status updates via SSE."""
    session_id = request.query_params.get("session_id", "default")
    
    async def event_stream():
        try:
            assistant = _get_voice_assistant(session_id)
            
            # Start continuous listening
            assistant.start_continuous_listening()
            
            def status_callback(status: str):
                # This would need to be integrated with the streaming mechanism
                pass
            
            # Stream transcriptions as they become available
            while True:
                try:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        break
                    
                    # Try to get next utterance with timeout
                    text = assistant.listen_once(continuous=True, timeout=0.25)
                    
                    if text and text.strip():
                        yield f"data: {json.dumps({'type': 'transcription', 'text': text})}\n\n"
                    
                    # Send heartbeat
                    yield ": keepalive\n\n"
                    
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': _voice_failure('stream', e)})}\n\n"
                    break
                    
        finally:
            # Cleanup
            try:
                assistant = _get_voice_assistant(session_id)
                assistant.stop_continuous_listening()
            except:
                pass
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.patch("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, request: Request):
    """Update a cron job."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if "interval_minutes" in body:
        interval = body["interval_minutes"]
        if not isinstance(interval, int) or interval <= 0:
            raise HTTPException(status_code=400, detail="interval_minutes must be a positive integer")
    job = _get_cron_queue().update_cron_job(
        job_id,
        enabled=body.get("enabled") if "enabled" in body else None,
        interval_minutes=body.get("interval_minutes") if "interval_minutes" in body else None,
        name=body.get("name") if "name" in body else None,
        prompt=body.get("prompt") if "prompt" in body else None,
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found")
    return {"status": "success", "job": job}


@app.post("/api/cron/jobs/{job_id}/run")
def run_cron_job(job_id: str):
    """Manually trigger a cron job."""
    run = _get_cron_queue().enqueue_cron_run(job_id, trigger="manual")
    if run is None:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found")
    return {"status": "accepted", **run}


@app.delete("/api/cron/jobs/{job_id}")
def delete_cron_job(job_id: str):
    """Disable a cron job while preserving historical runs."""
    if not _get_cron_queue().delete_cron_job(job_id):
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found")
    return {"status": "success", "enabled": False}


@app.get("/api/billing/status")
def billing_status():
    """Return billing status (local-first, always free)."""
    return {
        "status": "ok",
        "tier": "local",
        "message": "NEXUS AI is local-first - no billing required",
        "usage": {},
        "limits": {}
    }


@app.get("/api/providers")
def list_provider_config():
    """List configured providers from nexus config and kernel factory."""
    providers = _config_summary()["providers"]

    try:
        from models.providers.core.factory import NexusProviderFactory
        factory = NexusProviderFactory()
    except Exception:
        factory = None

    active_providers_from_kernel = set()
    if factory:
        try:
            from models.providers.core.profiles import load_profile_store
            store = load_profile_store()
            for prov in store.providers():
                active_providers_from_kernel.add(prov.lower())
        except Exception:
            logger.warning("server:1110 list_provider_config: suppressed error", exc_info=True)
            pass

    for p in providers:
        if p["id"].lower() in active_providers_from_kernel:
            p["active"] = True

    diagnostics = _provider_runtime_diagnostics()
    return {
        "providers": providers,
        "runtime": {
            "provider": _RUNTIME_SETTINGS.get("provider") or "",
            "model": _RUNTIME_SETTINGS.get("model") or "",
            "profile": _RUNTIME_SETTINGS.get("profile") or "",
        },
        "diagnostics": diagnostics,
        # Keep the explicit name available to status-oriented clients while
        # retaining the concise ``diagnostics`` field used by the settings UI.
        "provider_diagnostics": diagnostics,
    }


@app.get("/api/features")
def list_features():
    """List runtime feature flags from settings.yml."""
    return {"features": _config_summary()["features"]}


@app.get("/api/evolution")
def list_evolution():
    """List evolution system status and components."""
    config = _load_nexus_config()
    features = _runtime_features(config)
    enabled = features.get("evolution", False)
    
    # Try to get evolution components from the evolution module
    lifecycle = []
    forges = []
    try:
        from evolution.version_manager import VersionManager
        vm = VersionManager()
        lifecycle.append({
            "id": "version_manager",
            "name": "Version Manager",
            "available": True,
            "enabled": True,
            "description": "Manages versioning and rollback capabilities"
        })
    except Exception:
        pass
    
    try:
        from evolution.self_improvement import SelfImprovementEngine
        lifecycle.append({
            "id": "self_improvement",
            "name": "Self Improvement",
            "available": True,
            "enabled": True,
            "description": "Automated self-improvement through training"
        })
    except Exception:
        pass
    
    # Add forge modules
    forges.append({
        "id": "code_forge",
        "name": "Code Forge",
        "available": True,
        "enabled": True,
        "description": "Generates code artifacts"
    })
    forges.append({
        "id": "test_forge",
        "name": "Test Forge", 
        "available": True,
        "enabled": True,
        "description": "Generates test cases"
    })
    
    return {
        "enabled": enabled,
        "version": "1.0.0",
        "lifecycle": lifecycle,
        "forges": forges
    }


@app.get("/api/config/files")
def list_config_files():
    """List all configuration files in the project."""
    import os
    from pathlib import Path
    
    config_files = []
    project_root = _PROJECT_ROOT
    config_extensions = ['.json', '.yaml', '.yml', '.jsnol']
    
    # Search in key directories
    search_dirs = [
        os.path.join(project_root, 'configure'),
        os.path.join(project_root, 'workspace'),
        os.path.join(project_root, 'skills'),
        os.path.join(project_root, 'tools'),
        os.path.join(project_root, 'plugins'),
        os.path.join(project_root, 'mcp'),
        os.path.join(project_root, 'hive'),
        os.path.join(project_root, 'evolution'),
        os.path.join(project_root, 'safety'),
        os.path.join(project_root, 'voice'),
        os.path.join(project_root, 'providers'),
        os.path.join(project_root, 'knowledge'),
    ]
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            # Skip node_modules and other common exclusions
            dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.git', 'venv']]
            
            for file in files:
                if any(file.endswith(ext) for ext in config_extensions):
                    rel_path = os.path.relpath(os.path.join(root, file), project_root)
                    config_files.append({
                        "name": file,
                        "path": rel_path,
                        "size": os.path.getsize(os.path.join(root, file)),
                        "type": file.split('.')[-1]
                    })
    
    return {"files": sorted(config_files, key=lambda x: x['path'])}


@app.get("/api/config/file")
def get_config_file(path: str):
    """Read a specific configuration file."""
    import os
    from pathlib import Path
    
    # Security check - ensure path is within project root
    project_root = _PROJECT_ROOT
    full_path = os.path.join(project_root, path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    if _is_sensitive_workspace_path(full_path):
        raise HTTPException(status_code=403, detail="Sensitive files cannot be read through the API")
    
    try:
        within_root = os.path.commonpath((os.path.realpath(full_path), os.path.realpath(project_root))) == os.path.realpath(project_root)
    except ValueError:
        within_root = False
    if not within_root:
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "path": path,
            "content": content,
            "size": os.path.getsize(full_path)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Workspace file read", e))


@app.post("/api/approve")
async def approve_tool_request(request: Request):
    """Resolve a pending Co-Pilot (ask-mode) tool approval.

    The GUI has always POSTed here from useStreamChat.respondApproval(), but
    no backend route existed, so ask-mode approvals went nowhere and the run
    stalled until it timed out. Decisions are brokered by
    permissions.approval_broker so any surface can answer.
    """
    from security.permissions.approval_broker import get_approval_broker, normalize_decision

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
    from security.permissions.approval_broker import get_approval_broker

    return {"pending": get_approval_broker().pending(safe_session_id(session_id) if session_id else "")}


@app.get("/api/files/read")
def read_workspace_file(path: str = "", format: str = ""):
    """Stream a single workspace file for the GUI file explorer / download.

    The frontend (FileExplorer.tsx, lib/api.ts) has always linked to this
    route, but no backend implemented it, so every preview/download 404'd.
    Path containment is enforced by safe_workspace_read_path().
    """
    resolved = safe_workspace_read_path(path)
    if str(format).lower() in {"json", "text"}:
        try:
            with open(resolved, "r", encoding="utf-8") as handle:
                content = handle.read()
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="File is not UTF-8 text")
        return {"path": path, "content": content}
    from fastapi.responses import FileResponse
    return FileResponse(
        resolved,
        filename=os.path.basename(resolved),
        media_type="application/octet-stream",
    )


def _safe_workspace_mutation_path(raw_path: str, *, must_exist: bool = False) -> str:
    """Resolve a GUI file-operation path without following it outside the workspace."""
    value = str(raw_path or "").strip().strip('"').strip("'")
    if not value:
        raise HTTPException(status_code=400, detail="Path is required")
    candidate = value if os.path.isabs(value) else os.path.join(_PROJECT_ROOT, value)
    root = os.path.realpath(os.path.abspath(_PROJECT_ROOT))
    path = os.path.realpath(os.path.abspath(candidate))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:
        inside = False
    if not inside or path == root:
        raise HTTPException(status_code=403, detail="Path is outside the NEXUS workspace")
    if must_exist and not os.path.lexists(path):
        raise HTTPException(status_code=404, detail="Path not found")
    return path


async def _file_json(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    return data


def _invalidate_verifier_after_file_mutation(session_id: Any, *paths: Any) -> None:
    """Mark workspace verifier state stale after an API-side mutation."""
    try:
        from nexus.main_agent.verification_state import VerifierStateStore

        state_path = Path(_PROJECT_ROOT) / ".nexus_v5" / "verifier_state.json"
        VerifierStateStore(state_path).mark_stale(
            safe_session_id(str(session_id or "default")), _PROJECT_ROOT, paths
        )
    except Exception:
        logger.debug("Could not invalidate verifier state after file mutation", exc_info=True)


def _write_workspace_file_sync(path: str, content: str) -> None:
    if os.path.exists(path) and os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Cannot write a directory")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _create_workspace_file_sync(path: str, kind: str) -> None:
    if os.path.lexists(path):
        raise HTTPException(status_code=409, detail="Path already exists")
    os.makedirs(path if kind == "folder" else os.path.dirname(path), exist_ok=True)
    if kind == "file":
        with open(path, "x", encoding="utf-8"):
            pass


def _rename_workspace_file_sync(source: str, target: str) -> None:
    if os.path.lexists(target):
        raise HTTPException(status_code=409, detail="Destination already exists")
    os.replace(source, target)


def _delete_workspace_file_sync(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _move_workspace_file_sync(source: str, destination: str) -> str:
    if os.path.isdir(destination):
        destination = os.path.join(destination, os.path.basename(source))
    if os.path.lexists(destination):
        raise HTTPException(status_code=409, detail="Destination already exists")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.move(source, destination)
    return destination


def _zip_workspace_file_sync(source: str, target: str) -> None:
    import zipfile

    if os.path.lexists(target):
        raise HTTPException(status_code=409, detail="Archive already exists")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        if os.path.isdir(source):
            for directory, _, files in os.walk(source):
                for filename in files:
                    full = os.path.join(directory, filename)
                    archive.write(full, os.path.relpath(full, os.path.dirname(source)))
        else:
            archive.write(source, os.path.basename(source))


def _unzip_workspace_file_sync(source: str, destination: str) -> None:
    import zipfile

    if not zipfile.is_zipfile(source):
        raise HTTPException(status_code=400, detail="Source is not a ZIP archive")
    os.makedirs(destination, exist_ok=True)
    root = os.path.realpath(destination)
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            target = os.path.realpath(os.path.join(destination, member.filename))
            try:
                inside = os.path.commonpath([root, target]) == root
            except ValueError:
                inside = False
            if not inside:
                raise HTTPException(status_code=400, detail="Archive contains an unsafe path")
        archive.extractall(destination)


def _list_workspace_files_sync(
    target: str, project_root: str, display_path: str = "."
) -> List[Dict[str, Any]]:
    try:
        entries = sorted(os.listdir(target))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {display_path}")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=_public_api_failure("Workspace directory listing", exc),
        )

    files = []
    for name in entries:
        if name.lower() in _WINDOWS_RESERVED or name.endswith("."):
            continue
        full_path = os.path.join(target, name)
        try:
            rel_path = os.path.relpath(full_path, project_root).replace("\\", "/")
        except ValueError:
            rel_path = name
        files.append({
            "name": name,
            "path": rel_path,
            "isDirectory": os.path.isdir(full_path),
            "children": [],
        })
    return files


@app.post("/api/files/write")
async def write_workspace_file(request: Request):
    data = await _file_json(request)
    path = _safe_workspace_mutation_path(data.get("path"))
    content = data.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be text")
    await asyncio.to_thread(_write_workspace_file_sync, path, content)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), path)
    return {"status": "ok", "path": os.path.relpath(path, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/create")
async def create_workspace_file(request: Request):
    data = await _file_json(request)
    path = _safe_workspace_mutation_path(data.get("path"))
    kind = str(data.get("type") or "file").lower()
    if kind not in {"file", "folder"}:
        raise HTTPException(status_code=400, detail="type must be file or folder")
    await asyncio.to_thread(_create_workspace_file_sync, path, kind)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), path)
    return {"status": "ok", "path": os.path.relpath(path, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/rename")
async def rename_workspace_file(request: Request):
    data = await _file_json(request)
    source = _safe_workspace_mutation_path(data.get("path"), must_exist=True)
    name = os.path.basename(str(data.get("name") or "").strip())
    if not name or name in {".", ".."} or name != str(data.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="name must be a single path component")
    target = _safe_workspace_mutation_path(os.path.join(os.path.dirname(source), name))
    await asyncio.to_thread(_rename_workspace_file_sync, source, target)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), source, target)
    return {"status": "ok", "path": os.path.relpath(target, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/delete")
async def delete_workspace_file(request: Request):
    data = await _file_json(request)
    path = _safe_workspace_mutation_path(data.get("path"), must_exist=True)
    await asyncio.to_thread(_delete_workspace_file_sync, path)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), path)
    return {"status": "ok"}


@app.post("/api/files/move")
async def move_workspace_file(request: Request):
    data = await _file_json(request)
    source = _safe_workspace_mutation_path(data.get("source"), must_exist=True)
    destination = _safe_workspace_mutation_path(data.get("dest"))
    destination = await asyncio.to_thread(_move_workspace_file_sync, source, destination)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), source, destination)
    return {"status": "ok", "path": os.path.relpath(destination, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/zip")
async def zip_workspace_file(request: Request):
    data = await _file_json(request)
    source = _safe_workspace_mutation_path(data.get("source"), must_exist=True)
    target = _safe_workspace_mutation_path(source + ".zip")
    await asyncio.to_thread(_zip_workspace_file_sync, source, target)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), target)
    return {"status": "ok", "path": os.path.relpath(target, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/unzip")
async def unzip_workspace_file(request: Request):
    data = await _file_json(request)
    source = _safe_workspace_mutation_path(data.get("source"), must_exist=True)
    destination = _safe_workspace_mutation_path(os.path.splitext(source)[0])
    await asyncio.to_thread(_unzip_workspace_file_sync, source, destination)
    _invalidate_verifier_after_file_mutation(data.get("session_id"), destination)
    return {"status": "ok", "path": os.path.relpath(destination, _PROJECT_ROOT).replace("\\", "/")}


@app.post("/api/files/list")
async def list_files(request: Request):
    """List directory contents relative to project root."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    relative_path = str(data.get("path", ".")).strip()

    project_root_real = os.path.realpath(os.path.abspath(_PROJECT_ROOT))
    target = os.path.realpath(os.path.abspath(os.path.join(project_root_real, relative_path)))
    try:
        inside = os.path.commonpath([project_root_real, target]) == project_root_real
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=403, detail="Path is outside project root")

    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail=f"Path not found: {relative_path}")

    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {relative_path}")

    files = await asyncio.to_thread(
        _list_workspace_files_sync, target, _PROJECT_ROOT, relative_path
    )

    return {"files": files}


# ─────────────────────────────────────────────────────────────────────────────
# Workspace checkpoints (restore points for file-changing runs)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_checkpoint_id(checkpoint_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", str(checkpoint_id or ""))[:80]
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid checkpoint id")
    return cleaned


def _should_skip_checkpoint_rel(rel: str) -> bool:
    parts = str(rel or "").replace("\\", "/").split("/")
    if any(part in _CHECKPOINT_SKIP_NAMES for part in parts):
        return True
    last = parts[-1] if parts else ""
    if os.path.splitext(last)[1].lower() in _CHECKPOINT_SKIP_SUFFIXES:
        return True
    return last.lower() in _WINDOWS_RESERVED


def _create_workspace_checkpoint(workspace_root: str, session_id: str, run_id: str, turn_id: str = "") -> Dict[str, Any]:
    """Copy the snapshot-scope workspace into a new checkpoint dir."""
    root = os.path.abspath(workspace_root or _workspace_root())
    ckpt_id = uuid.uuid4().hex
    ckpt_root = os.path.join(_CHECKPOINTS_ROOT, ckpt_id)
    snapshot_root = os.path.join(ckpt_root, "snapshot")
    
    try:
        os.makedirs(snapshot_root, exist_ok=True)
        manifest: List[str] = []
        file_count = 0
        size_bytes = 0
        for dirpath, dirnames, filenames in os.walk(root):
            pruned = []
            for name in sorted(dirnames):
                rel_dir = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
                if not _should_skip_checkpoint_rel(rel_dir):
                    pruned.append(name)
            dirnames[:] = pruned
            for fn in sorted(filenames):
                src = os.path.join(dirpath, fn)
                if os.path.islink(src):
                    continue
                rel = os.path.relpath(src, root).replace("\\", "/")
                if _should_skip_checkpoint_rel(rel):
                    continue
                dst = os.path.join(snapshot_root, rel)
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    size_bytes += os.path.getsize(src)
                    manifest.append(rel)
                    file_count += 1
                except (OSError, shutil.Error):
                    continue
        manifest.sort()
        meta = {
            "checkpoint_id": ckpt_id,
            "session_id": safe_session_id(session_id),
            "run_id": str(run_id or ""),
            "turn_id": str(turn_id or run_id or ""),
            "created_at": time.time(),
            "file_count": file_count,
            "size_bytes": size_bytes,
            "workspace_root": root,
        }
        
        # Atomic write for metadata.json
        meta_path = os.path.join(ckpt_root, "metadata.json")
        meta_tmp = f"{meta_path}.tmp"
        with open(meta_tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        os.replace(meta_tmp, meta_path)
        
        # Atomic write for manifest.json
        manifest_path = os.path.join(ckpt_root, "manifest.json")
        manifest_tmp = f"{manifest_path}.tmp"
        with open(manifest_tmp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        os.replace(manifest_tmp, manifest_path)
        
        # Validate checkpoint is complete
        if not os.path.isfile(meta_path) or not os.path.isfile(manifest_path):
            raise OSError("Checkpoint files not written successfully")
        
        return meta
    except Exception:
        # Clean up incomplete checkpoint on any failure
        if os.path.isdir(ckpt_root):
            shutil.rmtree(ckpt_root, ignore_errors=True)
        raise


def _validate_checkpoint_integrity(ckpt_root: str) -> Tuple[bool, List[str]]:
    """Validate checkpoint structure and return (is_valid, errors)."""
    errors = []
    
    # Check directory exists
    if not os.path.isdir(ckpt_root):
        errors.append("Checkpoint directory does not exist")
        return False, errors
    
    # Check required files
    meta_path = os.path.join(ckpt_root, "metadata.json")
    manifest_path = os.path.join(ckpt_root, "manifest.json")
    snapshot_root = os.path.join(ckpt_root, "snapshot")
    
    if not os.path.isfile(meta_path):
        errors.append("metadata.json is missing")
    if not os.path.isfile(manifest_path):
        errors.append("manifest.json is missing")
    if not os.path.isdir(snapshot_root):
        errors.append("snapshot directory is missing")
    
    # Validate metadata.json
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            if not isinstance(meta, dict):
                errors.append("metadata.json is not a valid JSON object")
            elif not meta.get("checkpoint_id"):
                errors.append("metadata.json missing checkpoint_id")
        except json.JSONDecodeError:
            errors.append("metadata.json is not valid JSON")
        except OSError:
            errors.append("metadata.json is unreadable")
    
    # Validate manifest.json
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            if not isinstance(manifest, list):
                errors.append("manifest.json is not a valid JSON array")
        except json.JSONDecodeError:
            errors.append("manifest.json is not valid JSON")
        except OSError:
            errors.append("manifest.json is unreadable")
    
    return len(errors) == 0, errors


def _load_checkpoint_meta(ckpt_root: str) -> Dict[str, Any]:
    meta_path = os.path.join(ckpt_root, "metadata.json")
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=400, detail="Checkpoint is corrupt: metadata unreadable")
    if not isinstance(meta, dict) or not meta.get("checkpoint_id"):
        raise HTTPException(status_code=400, detail="Checkpoint is corrupt: invalid metadata")
    return meta


def _restore_workspace_checkpoint(workspace_root: str, session_id: str, checkpoint_id: str) -> Dict[str, Any]:
    ws_root = os.path.abspath(workspace_root or _workspace_root())
    ckpt_root = os.path.join(_CHECKPOINTS_ROOT, _safe_checkpoint_id(checkpoint_id))
    
    # Check if checkpoint directory exists first (404 if not)
    if not os.path.isdir(ckpt_root):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    
    # Validate checkpoint integrity for existing checkpoints (400 if corrupt)
    is_valid, errors = _validate_checkpoint_integrity(ckpt_root)
    if not is_valid:
        error_detail = f"Checkpoint is corrupt: {', '.join(errors)}"
        raise HTTPException(status_code=400, detail=error_detail)
    
    meta = _load_checkpoint_meta(ckpt_root)
    sid = safe_session_id(session_id or str(meta.get("session_id") or ""))
    if meta.get("session_id") and str(meta["session_id"]) != sid:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    
    snapshot_root = os.path.join(ckpt_root, "snapshot")
    manifest_path = os.path.join(ckpt_root, "manifest.json")
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=400, detail="Checkpoint is corrupt: manifest unreadable")
    if not isinstance(manifest, list):
        raise HTTPException(status_code=400, detail="Checkpoint is corrupt: invalid manifest")

    restored: List[str] = []
    removed: List[str] = []
    failures: List[Dict[str, str]] = []

    def _safe_target(rel: str) -> str:
        if not rel or os.path.isabs(rel):
            raise ValueError("invalid path")
        norm = os.path.normpath(rel)
        if norm.startswith("..") or os.path.isabs(norm):
            raise ValueError("invalid path")
        target = os.path.abspath(os.path.join(ws_root, norm))
        if not _is_within(ws_root, target):
            raise ValueError("path escapes workspace")
        return target

    def _atomic_copy(src: str, dst: str) -> None:
        tmp = f"{dst}.nexus-restore-{uuid.uuid4().hex[:8]}.tmp"
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    manifest_set = {str(item) for item in manifest}
    for rel in manifest:
        rel = str(rel)
        try:
            target = _safe_target(rel)
            src = os.path.abspath(os.path.join(snapshot_root, rel))
            if not _is_within(snapshot_root, src) or not os.path.isfile(src):
                raise ValueError("snapshot file missing")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _atomic_copy(src, target)
            restored.append(rel)
        except Exception as exc:
            failures.append({"path": rel, "error": str(exc)})

    added: List[str] = []
    for dirpath, dirnames, filenames in os.walk(ws_root):
        pruned = []
        for name in sorted(dirnames):
            rel_dir = os.path.relpath(os.path.join(dirpath, name), ws_root).replace("\\", "/")
            if not _should_skip_checkpoint_rel(rel_dir):
                pruned.append(name)
        dirnames[:] = pruned
        for fn in filenames:
            if fn.lower() in _WINDOWS_RESERVED or fn.endswith("."):
                continue
            full = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(full, ws_root).replace("\\", "/")
            except ValueError:
                continue
            if _should_skip_checkpoint_rel(rel):
                continue
            if rel in manifest_set:
                continue
            added.append(full)
    for full in added:
        try:
            rel = os.path.relpath(full, ws_root).replace("\\", "/")
        except ValueError:
            continue
        try:
            os.remove(full)
            removed.append(rel)
        except Exception as exc:
            failures.append({"path": rel, "error": str(exc)})

    for dirpath, dirnames, filenames in os.walk(ws_root, topdown=False):
        try:
            if os.path.isdir(dirpath) and not os.listdir(dirpath):
                rel_dir = os.path.relpath(dirpath, ws_root).replace("\\", "/")
                if rel_dir != "." and not _should_skip_checkpoint_rel(rel_dir):
                    os.rmdir(dirpath)
        except (OSError, ValueError):
            continue

    return {
        "checkpoint_id": _safe_checkpoint_id(checkpoint_id),
        "session_id": sid,
        "ok": len(failures) == 0,
        "restored": len(restored),
        "removed": len(removed),
        "failed": len(failures),
        "failures": failures,
        "messages": [
            f"Restored {len(restored)} file(s) and removed {len(removed)} added file(s) from {ws_root}."
        ],
        "workspace_root": ws_root,
    }


def _register_checkpoint_pusher(run_id: str, pusher: Any) -> None:
    if not run_id:
        return
    with _CHECKPOINT_STREAM_PUSHERS_LOCK:
        _CHECKPOINT_STREAM_PUSHERS[run_id] = pusher
        if len(_CHECKPOINT_STREAM_PUSHERS) > 64:
            for stale in list(_CHECKPOINT_STREAM_PUSHERS)[:32]:
                _CHECKPOINT_STREAM_PUSHERS.pop(stale, None)


def _unregister_checkpoint_pusher(run_id: str) -> None:
    if not run_id:
        return
    with _CHECKPOINT_STREAM_PUSHERS_LOCK:
        _CHECKPOINT_STREAM_PUSHERS.pop(run_id, None)


def _emit_checkpoint_created(session_id: str, run_id: str, turn_id: str, meta: Dict[str, Any]) -> None:
    event = {
        "event_type": "checkpoint.created",
        "kind": "checkpoint",
        "type": "checkpoint",
        "status": "done",
        "title": "File checkpoint created",
        "action": "Snapshot created",
        "target": "workspace",
        "id": f"ckpt_{turn_id}_{meta['checkpoint_id'][:8]}",
        "run_id": run_id,
        "turn_id": turn_id,
        "checkpoint_id": meta["checkpoint_id"],
        "file_count": meta.get("file_count", 0),
        "size_bytes": meta.get("size_bytes", 0),
        "created_at": meta.get("created_at", time.time()),
        "visibility": "public",
    }
    _append_work_event(session_id, event)
    pusher = None
    with _CHECKPOINT_STREAM_PUSHERS_LOCK:
        pusher = _CHECKPOINT_STREAM_PUSHERS.get(run_id) or _CHECKPOINT_STREAM_PUSHERS.get(str(turn_id))
    if pusher:
        try:
            pusher(event)
        except Exception:
            logger.debug("checkpoint.created live push failed", exc_info=True)


def _maybe_trigger_checkpoint(session_id: str, event: Dict[str, Any]) -> None:
    """Snapshot the workspace once per run, just before tools begin executing."""
    try:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        # Canonical envelopes expose the type as `type` (not `event_type`), and
        # fold the loop's `state` inside `payload`; accept both shapes.
        event_type = str(
            event.get("event_type") or event.get("type")
            or payload.get("event_type") or payload.get("type")
            or nested.get("event_type") or nested.get("type") or ""
        )
        state = str(event.get("state") or payload.get("state") or nested.get("state") or "")
        executing = event_type == "run.status" and state == "execution"
        if not executing and event_type not in ("plan.step.started", "tool.queued"):
            return
        run_id = str(event.get("run_id") or event.get("turn_id") or "")
        if not run_id:
            return
        with _CHECKPOINT_GUARD_LOCK:
            status = _CHECKPOINT_GUARD.get(run_id)
            if status in ("creating", "done"):
                return
            _CHECKPOINT_GUARD[run_id] = "creating"
            if len(_CHECKPOINT_GUARD) > 512:
                for stale in list(_CHECKPOINT_GUARD)[:256]:
                    _CHECKPOINT_GUARD.pop(stale, None)
        turn_id = str(event.get("turn_id") or run_id)
        sid = safe_session_id(session_id)
        ws_root = _workspace_root()

        def worker() -> None:
            try:
                meta = _create_workspace_checkpoint(ws_root, sid, run_id, turn_id)
                _emit_checkpoint_created(sid, run_id, turn_id, meta)
            except Exception:
                logger.warning("checkpoint creation failed for run %s", run_id, exc_info=True)
            finally:
                with _CHECKPOINT_GUARD_LOCK:
                    _CHECKPOINT_GUARD[run_id] = "done"

        threading.Thread(target=worker, name="checkpoint-snapshot", daemon=True).start()
    except Exception:
        logger.debug("checkpoint trigger failed", exc_info=True)


@app.get("/api/checkpoints")
def list_checkpoints(session_id: str = ""):
    """List workspace checkpoints, newest first."""
    sid = safe_session_id(session_id) if session_id else ""
    results = []
    if os.path.isdir(_CHECKPOINTS_ROOT):
        for name in sorted(os.listdir(_CHECKPOINTS_ROOT), reverse=True):
            ckpt_root = os.path.join(_CHECKPOINTS_ROOT, name)
            if not os.path.isdir(ckpt_root):
                continue
            try:
                meta = _load_checkpoint_meta(ckpt_root)
            except HTTPException:
                continue
            if sid and str(meta.get("session_id") or "") != sid:
                continue
            results.append({
                "checkpoint_id": str(meta["checkpoint_id"]),
                "session_id": str(meta.get("session_id") or ""),
                "run_id": str(meta.get("run_id") or ""),
                "turn_id": str(meta.get("turn_id") or ""),
                "created_at": meta.get("created_at", 0),
                "file_count": meta.get("file_count", 0),
                "size_bytes": meta.get("size_bytes", 0),
            })
    return {"checkpoints": results}


@app.post("/api/checkpoints/{checkpoint_id}/restore")
async def restore_checkpoint_endpoint(checkpoint_id: str, request: Request):
    """Restore a workspace checkpoint. Per-file failures are reported, not fatal."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    sid = safe_session_id(str(body.get("session_id") or ""))
    ckpt_id = _safe_checkpoint_id(checkpoint_id)
    with _CHECKPOINT_RESTORE_LOCKS_LOCK:
        lock = _CHECKPOINT_RESTORE_LOCKS.setdefault(ckpt_id, threading.Lock())
        if len(_CHECKPOINT_RESTORE_LOCKS) > 256:
            for stale in list(_CHECKPOINT_RESTORE_LOCKS)[:128]:
                _CHECKPOINT_RESTORE_LOCKS.pop(stale, None)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Restore already in progress for checkpoint {ckpt_id}")
    try:
        return await asyncio.to_thread(_restore_workspace_checkpoint, _workspace_root(), sid, ckpt_id)
    finally:
        lock.release()


@app.delete("/api/checkpoints/{checkpoint_id}")
def delete_checkpoint_endpoint(checkpoint_id: str, session_id: str = ""):
    """Delete a stored checkpoint snapshot."""
    sid = safe_session_id(session_id) if session_id else ""
    ckpt_root = os.path.join(_CHECKPOINTS_ROOT, _safe_checkpoint_id(checkpoint_id))
    if not os.path.isdir(ckpt_root):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    meta = _load_checkpoint_meta(ckpt_root)
    if sid and str(meta.get("session_id") or "") != sid:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    shutil.rmtree(ckpt_root, ignore_errors=True)
    return {"deleted": True}


def _persist_manage_config_sync(config: Dict[str, Any], sync_mcp: bool = False) -> None:
    """Persist one management mutation in a worker thread, preserving order."""
    _save_nexus_config(config)
    if sync_mcp:
        _sync_mcp_servers_file(config)


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
                from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
                ToolRegistry._reset_instance()
            except Exception:
                logger.warning("server:1208 : suppressed error", exc_info=True)
                pass
            _clear_runtime("tools reloaded")

        elif target_type in {"skill", "skills"}:
            try:
                from extensions.skills.built_in import NexusSkillMaster
                NexusSkillMaster._reset_instance()
            except Exception:
                logger.warning("server:1216 : suppressed error", exc_info=True)
                pass
            _clear_runtime("skills reloaded")

        elif target_type in {"mcp", "mcps", "mcp_server"}:
            _clear_runtime("mcp config reloaded")

        elif target_type in {"provider", "providers"}:
            try:
                from models.providers.core.factory import NexusProviderFactory
                NexusProviderFactory._reset_instance()
            except Exception:
                logger.warning("server:1227 : suppressed error", exc_info=True)
                pass
            _clear_runtime("providers reloaded")

        elif target_type == "config":
            try:
                from configure.config_loader import NexusConfigLoader
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
                "workspace_root": "",
            })
            await asyncio.to_thread(_save_runtime_preferences)
            reset = _clear_runtime("reset requested")
            return {"status": "success", "target": target_type or "runtime", **reset}
        if target_type == "tasks":
            _TASKS.clear()
            await asyncio.to_thread(_save_tasks, _TASKS)
            return {"status": "success", "target": "tasks", "cleared": True}
        raise HTTPException(status_code=400, detail=f"Reset not supported for {target_type}")

    if target_type in {"hive", "evolution", "scheduler", "reminders", "health"} and not name:
        name = target_type

    if not target_type or not name:
        raise HTTPException(status_code=400, detail="type and name are required")

    config = await asyncio.to_thread(_load_nexus_config)

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
        await asyncio.to_thread(_persist_manage_config_sync, config)
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
        await asyncio.to_thread(_persist_manage_config_sync, config)
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
        await asyncio.to_thread(_persist_manage_config_sync, config, True)
        _clear_runtime("mcp config changed")
        return {"status": "success", "type": "mcp", "name": name, "active": bool(entry.get("active", False)) if action != "remove" else False}

    if target_type in {"plugin", "plugins"}:
        def mutate_plugin_settings(settings):
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
            return bool(enabled.get(name, False))

        enabled = await asyncio.to_thread(_mutate_claude_settings_sync, mutate_plugin_settings)
        return {"status": "success", "type": "plugin", "name": name, "enabled": enabled}

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
        await asyncio.to_thread(_persist_manage_config_sync, config)
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
        await asyncio.to_thread(_persist_manage_config_sync, config)
        _clear_runtime("feature config changed")
        return {"status": "success", "type": "feature", "name": feature_name, "enabled": bool(features[feature_name])}

    if target_type == "config":
        if action != "set":
            raise HTTPException(status_code=400, detail="config supports only set")
        _set_dotted(config, name, value)
        await asyncio.to_thread(_persist_manage_config_sync, config)
        _clear_runtime("config changed")
        return {"status": "success", "type": "config", "path": name, "value": _parse_config_value(value)}

    if target_type == "runtime":
        if action != "set":
            raise HTTPException(status_code=400, detail="runtime supports only set")
        if not isinstance(value, (list, str)) and name not in {"additional_dirs"}:
            raise HTTPException(status_code=400, detail="runtime set expects a list value for additional_dirs")
        if name == "additional_dirs":
            if not isinstance(value, list):
                raise HTTPException(status_code=400, detail="additional_dirs must be a list of paths")
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            _RUNTIME_SETTINGS["additional_dirs"] = cleaned
            await asyncio.to_thread(_save_runtime_preferences)
            apply_runtime_to_all_loops()
            _record_workspace_activity("directory_set", f"{len(cleaned)} additional director{'' if len(cleaned) == 1 else 'ies'} configured", status="ok")
            return {"status": "success", "type": "runtime", "name": "additional_dirs", "value": cleaned}
        if name == "workspace_root":
            target = str(value).strip() if isinstance(value, str) else ""
            if target:
                validated = _validate_workspace_path(target)
                if not validated.get("valid"):
                    raise HTTPException(status_code=400, detail=validated.get("reason", "Invalid workspace path"))
                _RUNTIME_SETTINGS["workspace_root"] = validated.get("path", target)
            else:
                _RUNTIME_SETTINGS["workspace_root"] = ""
            await asyncio.to_thread(_save_runtime_preferences)
            _record_workspace_activity("root_changed", _RUNTIME_SETTINGS["workspace_root"] or "unset", status="ok")
            return {"status": "success", "type": "runtime", "name": "workspace_root", "value": _RUNTIME_SETTINGS["workspace_root"]}
        raise HTTPException(status_code=400, detail=f"runtime set does not support: {name}")

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
    await asyncio.to_thread(_save_tasks, _TASKS)
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
    await asyncio.to_thread(_save_tasks, _TASKS)
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

    configured_provider, configured_model = configured_provider_defaults()
    provider_name = _RUNTIME_SETTINGS.get("provider") or getattr(active_provider, "provider_name", "") or configured_provider or "auto"
    provider_status = _provider_reachability(provider_name)
    status = {
        "model": _RUNTIME_SETTINGS.get("model") or getattr(active_provider, "model", "") or configured_model or "auto",
        "mode": _normalize_permission_mode(_RUNTIME_SETTINGS.get("mode") or "auto"),
        "provider": provider_name,
        "agent": _RUNTIME_SETTINGS.get("agent") or "",
        "goal": _RUNTIME_SETTINGS.get("goal") or "",
        "sandbox_tier": _normalize_sandbox_tier(_RUNTIME_SETTINGS.get("sandbox_tier", "normal")),
        "permission_modes": ["auto", "all", "allowlist", "ask"],
        "permission_allowlist": _RUNTIME_SETTINGS.get("permission_allowlist") or [],
        "thinking": bool(_RUNTIME_SETTINGS.get("thinking", True)),
        "effort": str(_RUNTIME_SETTINGS.get("effort") or "medium"),
        "additional_dirs": _RUNTIME_SETTINGS.get("additional_dirs") or [],
        "workspace_root": _workspace_root(),
        # Backend health and model-provider reachability are separate.  A
        # running API with a stopped local model is degraded, not healthy.
        "health": "degraded" if provider_status.get("configured") and not provider_status.get("reachable") else "ok",
        "provider_status": provider_status,
        "provider_diagnostics": _provider_runtime_diagnostics(),
        "uptime": 0,
        "session_count": len(_LOOPS),
        "agent_count": real_agent_count,
        "task_count": len(_TASKS),
        "version": "2.1.0"
    }
    return status


@app.get("/api/memory/statistics")
def get_memory_statistics():
    """Return comprehensive memory statistics."""
    try:
        from memory import MemoryManager
        memory = MemoryManager(_PROJECT_ROOT)
        stats = memory.get_statistics()
        return {"status": "success", "statistics": stats}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory statistics", e)}


@app.post("/api/memory/search")
async def search_memory(request: Request):
    """Search across all memory types."""
    try:
        data = await request.json()
        query = data.get("query", "")
        memory_types = data.get("memory_types")
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        from memory import MemoryManager
        memory = MemoryManager(_PROJECT_ROOT)
        results = memory.search_memory(query, memory_types)
        
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory search", e)}


@app.post("/api/memory/export")
async def export_memory(request: Request):
    """Export memory data in JSON or text format."""
    try:
        data = await request.json()
        format = data.get("format", "json")
        
        from memory import MemoryManager
        memory = MemoryManager(_PROJECT_ROOT)
        exported = memory.export_memory(format)
        
        return {"status": "success", "format": format, "data": exported}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory export", e)}


@app.post("/api/memory/import")
async def import_memory(request: Request):
    """Import memory data from JSON or text format."""
    try:
        data = await request.json()
        import_data = data.get("data", "")
        format = data.get("format", "json")
        
        if not import_data:
            raise HTTPException(status_code=400, detail="Data is required")
        
        from memory import MemoryManager
        memory = MemoryManager(_PROJECT_ROOT)
        success = memory.import_memory(import_data, format)
        
        if success:
            return {"status": "success", "message": "Memory imported successfully"}
        else:
            return {"status": "error", "message": "Memory import failed"}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory import", e)}


@app.post("/api/memory/clear")
async def clear_memory(request: Request):
    """Clear specific or all memory types."""
    try:
        data = await request.json()
        memory_type = data.get("memory_type", "all")
        
        from memory import MemoryManager
        memory = MemoryManager(_PROJECT_ROOT)
        memory.clear_memory(memory_type)
        
        return {"status": "success", "message": f"Cleared {memory_type} memory"}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory clear", e)}


@app.get("/api/memory/sessions")
def list_memory_sessions():
    """List all available memory sessions."""
    try:
        sess_dir = os.path.join(_PROJECT_ROOT, "logs", "sessions")
        sessions = []
        
        if os.path.isdir(sess_dir):
            for f in os.listdir(sess_dir):
                if f.endswith(".json"):
                    path = os.path.join(sess_dir, f)
                    stat = os.stat(path)
                    sessions.append({
                        "id": f[:-5],  # Remove .json
                        "file": f,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "modified_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                    })
        
        sessions.sort(key=lambda x: x["modified"], reverse=True)
        return {"status": "success", "sessions": sessions, "count": len(sessions)}
    except Exception as e:
        return {"status": "error", "message": _public_api_failure("Memory session listing", e)}


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
    await asyncio.to_thread(_save_runtime_preferences)
    try:
        from security.policies.safety_store import sync_permission_from_legacy
        sync_permission_from_legacy(mode)
    except Exception:
        logger.warning("safety: could not sync permission mode from legacy mode %s", mode, exc_info=True)
    return {"status": "success", "mode": mode}


@app.get("/api/permissions")
def get_permissions():
    """Return permission mode and saved allow-list."""
    from security.permissions import PermissionSystem

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
    from security.permissions import PermissionSystem

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
    await asyncio.to_thread(_save_runtime_preferences)
    try:
        from security.policies.safety_store import sync_permission_from_legacy
        sync_permission_from_legacy(mode)
    except Exception:
        logger.warning("safety: could not sync permission mode from /permissions", exc_info=True)
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
    provider = str(data.get("provider", "")).strip().lower().replace(" ", "_")
    profile = str(data.get("profile", "")).strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    if provider:
        _RUNTIME_SETTINGS["provider"] = provider
        if not profile:
            _RUNTIME_SETTINGS["profile"] = ""
    if profile:
        if not provider:
            raise HTTPException(status_code=400, detail="provider is required when selecting a profile")
        try:
            from models.providers.core.profiles import load_profile_store
            selected = load_profile_store().get_profile(provider, profile)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Provider profile store is unavailable") from exc
        if selected is None:
            raise HTTPException(status_code=409, detail=f"Provider profile '{profile}' is unavailable or disabled")
        native_model = str(getattr(selected, "model_id", "") or getattr(selected, "model", "") or model).strip()
        if native_model and model != native_model:
            model = native_model
        _RUNTIME_SETTINGS["profile"] = profile
    _RUNTIME_SETTINGS["model"] = model
    apply_runtime_to_all_loops()
    await asyncio.to_thread(_save_runtime_preferences)
    return {"status": "success", "model": model, "provider": _RUNTIME_SETTINGS.get("provider", ""), "profile": _RUNTIME_SETTINGS.get("profile", "")}


@app.post("/api/provider")
async def set_provider(request: Request):
    """Switch provider override."""
    data = await request.json()
    provider = str(data.get("provider", "")).strip().lower().replace(" ", "_")
    if provider in {"clear", "reset", "off", "auto"}:
        provider = ""
    _RUNTIME_SETTINGS["provider"] = provider
    apply_runtime_to_all_loops()
    await asyncio.to_thread(_save_runtime_preferences)
    return {"status": "success", "provider": provider}


@app.post("/api/agent")
async def set_agent(request: Request):
    """Switch agent."""
    data = await request.json()
    agent = str(data.get("agent", "")).strip()
    _RUNTIME_SETTINGS["agent"] = agent
    apply_runtime_to_all_loops()
    return {"status": "success", "agent": agent}


@app.get("/api/commands")
def list_commands():
    """Expose the central command registry to every client UI."""
    from nexus.commands import get_registry

    commands = []
    for command in get_registry().list():
        commands.append({
            "name": f"/{command.name}",
            "description": command.description,
            "category": command.category,
            "args": dict(command.args),
            "aliases": [f"/{alias.lstrip('/')}" for alias in command.aliases],
            "execution": command.execution,
        })
    return {"commands": commands}


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

    from nexus.common.session_bus import get_active_session_id
    requested_session = str(data.get("session_id") or "").strip()
    session_id = safe_session_id(requested_session) if requested_session else get_active_session_id(
        _PROJECT_ROOT, str(_RUNTIME_SETTINGS.get("session_id") or "default")
    )
    ctx = CommandContext(
        session_id=session_id,
        mode=_RUNTIME_SETTINGS.get("mode", "auto"),
        provider=_RUNTIME_SETTINGS.get("provider", ""),
        model=_RUNTIME_SETTINGS.get("model", ""),
        thinking=_RUNTIME_SETTINGS.get("thinking", True),
        extra={
            "args": args_raw,
            "command": raw,
            "root": str(_PROJECT_ROOT),
            "runtime_settings": _RUNTIME_SETTINGS,
            "persist_runtime": _save_runtime_preferences,
            "apply_runtime": apply_runtime_to_all_loops,
            "new_session": create_session,
            "list_sessions": list_sessions,
            "load_session": _command_load_session,
            "load_history": get_history,
            "sync_permission_mode": _command_sync_permission_mode,
            "sync_sandbox_tier": _command_sync_sandbox_tier,
        },
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
    await asyncio.to_thread(_save_runtime_preferences)
    try:
        from security.policies.safety_store import sync_sandbox_from_legacy
        sync_sandbox_from_legacy(tier)
    except Exception:
        logger.warning("safety: could not sync sandbox mode from legacy tier %s", tier, exc_info=True)
    return {"status": "success", "tier": tier}


@app.get("/api/thinking")
def get_thinking():
    """Return whether reasoning/thinking is enabled."""
    return {"status": "success", "thinking": bool(_RUNTIME_SETTINGS.get("thinking", True))}


@app.post("/api/thinking")
async def set_thinking(request: Request):
    """Enable or disable chain-of-thought reasoning for tool calls and replies."""
    data = await request.json()
    enabled = bool(data.get("enabled", True))
    _RUNTIME_SETTINGS["thinking"] = enabled
    await asyncio.to_thread(_save_runtime_preferences)
    return {"status": "success", "thinking": enabled}


@app.get("/api/effort")
def get_effort():
    return {"status": "success", "effort": str(_RUNTIME_SETTINGS.get("effort") or "medium")}


@app.post("/api/effort")
async def set_effort(request: Request):
    data = await request.json()
    effort = str(data.get("effort") or "medium").strip().lower()
    if effort == "extra_high":
        effort = "xhigh"
    allowed = {"auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    if effort not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid effort. Choose from: {', '.join(sorted(allowed))}")
    _RUNTIME_SETTINGS["effort"] = "medium" if effort == "auto" else effort
    await asyncio.to_thread(_save_runtime_preferences)
    return {"status": "success", "effort": _RUNTIME_SETTINGS["effort"]}


# ── Safety settings API ──────────────────────────────────────────────────────
# Safety (Permission Mode / Sandbox Mode / policies) is stored separately from
# the workspace selection. Saving Safety settings must never change the
# workspace; opening Workspace settings must never lose Safety changes.

def _safety_apply_runtime():
    """Push the current Safety permission/sandbox modes into the runtime engine."""
    from security.policies.safety_store import get_state, PERMISSION_TO_LEGACY, SANDBOX_TO_LEGACY
    state = get_state(refresh=True)
    legacy_mode = PERMISSION_TO_LEGACY.get(state.get("permission_mode"), "auto")
    legacy_tier = SANDBOX_TO_LEGACY.get(state.get("sandbox_mode"), "normal")
    _RUNTIME_SETTINGS["mode"] = legacy_mode
    _RUNTIME_SETTINGS["sandbox_tier"] = legacy_tier
    os.environ["NEXUS_SANDBOX_TIER"] = legacy_tier
    apply_runtime_to_all_loops()
    _save_runtime_preferences()
    return {"permission_mode": state.get("permission_mode"), "sandbox_mode": state.get("sandbox_mode")}


@app.get("/api/safety/summary")
async def safety_summary():
    """Short summary for the header bar (workspace, modes, counts)."""
    try:
        from security.policies.safety_store import get_state, summary
        get_state(refresh=True)  # cross-process freshness (server may outlive a CLI edit)
        return summary()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: summary failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/settings")
async def safety_settings():
    """Full current Safety settings (no secrets ever included)."""
    try:
        from security.policies.safety_store import get_state
        return get_state(refresh=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: settings failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/meta")
async def safety_meta():
    """Static option lists for the Safety UI (modes, categories, policies)."""
    def as_list(mapping):
        if isinstance(mapping, dict):
            return [{"id": key, **value} for key, value in mapping.items()]
        return list(mapping)

    try:
        from security.policies.safety_store import _default_protected_paths, list_presets
        default_paths = _default_protected_paths()
        presets = list_presets()
    except Exception:  # pragma: no cover - defensive
        default_paths = []
        presets = []

    return {
        "permission_modes": as_list(_SAFETY_PERMISSION_MODES),
        "sandbox_modes": as_list(_SAFETY_SANDBOX_MODES),
        "command_categories": as_list(_SAFETY_COMMAND_CATEGORIES),
        "file_policy_categories": as_list(_SAFETY_FILE_POLICY_CATEGORIES),
        "filesystem_options": as_list(_SAFETY_FILESYSTEM_OPTIONS),
        "secret_protection_options": as_list(_SAFETY_SECRET_PROTECTION_OPTIONS),
        "network_policies": as_list(_SAFETY_NETWORK_POLICIES),
        "browser_options": as_list(_SAFETY_BROWSER_OPTIONS),
        "mcp_options": as_list(_SAFETY_MCP_OPTIONS),
        "package_options": as_list(_SAFETY_PACKAGE_OPTIONS),
        "package_managers": as_list(_SAFETY_PACKAGE_MANAGERS),
        "process_options": as_list(_SAFETY_PROCESS_OPTIONS),
        "destructive_actions": as_list(_SAFETY_DESTRUCTIVE_ACTIONS),
        "checkpoint_options": as_list(_SAFETY_CHECKPOINT_OPTIONS),
        "default_protected_paths": default_paths,
        "presets": presets,
    }


@app.post("/api/safety/save")
async def safety_save(request: Request):
    """Atomically save Safety settings. Never touches the workspace config."""
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        from security.policies.safety_store import save
        result = save(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: save failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid settings"])))
    if result.get("permission_changed") or result.get("sandbox_changed"):
        _safety_apply_runtime()
    result["workspace"] = _workspace_root()
    return result


@app.post("/api/safety/reset")
async def safety_reset(request: Request):
    """Reset Safety settings to defaults (workspace selection untouched)."""
    try:
        data = await request.json()
        confirm = bool((data or {}).get("confirm", False))
    except Exception:
        confirm = False
    if not confirm:
        raise HTTPException(status_code=400, detail="Reset requires confirm: true")
    try:
        from security.policies.safety_store import reset
        result = reset()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: reset failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    _safety_apply_runtime()
    result["workspace"] = _workspace_root()
    return result


@app.post("/api/safety/permission-mode")
async def safety_set_permission_mode(request: Request):
    """Set only the permission mode (7 modes). Sandbox + workspace untouched."""
    data = await request.json()
    mode = str((data or {}).get("mode", "")).strip()
    try:
        from security.policies.safety_store import set_permission_mode
        result = set_permission_mode(mode)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: set permission mode failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid mode"])))
    _safety_apply_runtime()
    return result


@app.post("/api/safety/sandbox-mode")
async def safety_set_sandbox_mode(request: Request):
    """Set only the sandbox mode (7 modes). Permission + workspace untouched."""
    data = await request.json()
    mode = str((data or {}).get("mode", "")).strip()
    try:
        from security.policies.safety_store import set_sandbox_mode
        result = set_sandbox_mode(mode)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: set sandbox mode failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid mode"])))
    _safety_apply_runtime()
    return result


@app.get("/api/safety/protected-paths")
async def safety_protected_paths():
    try:
        from security.policies.safety_store import get_state
        state = get_state(refresh=True)
        return {"paths": state.get("protected_paths", []), "mandatory": state.get("mandatory_protected_paths", [])}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: protected paths failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/protected-paths")
async def safety_add_protected_path(request: Request):
    data = await request.json()
    try:
        from security.policies.safety_store import add_protected_path
        result = add_protected_path(data or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: add protected path failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid protected path"])))
    return result


@app.patch("/api/safety/protected-paths")
async def safety_update_protected_path(request: Request):
    data = await request.json()
    pattern = str((data or {}).get("pattern", "")).strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    try:
        from security.policies.safety_store import update_protected_path
        result = update_protected_path(pattern, data or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: update protected path failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid protected path"])))
    return result


@app.delete("/api/safety/protected-paths")
async def safety_remove_protected_path(request: Request):
    data = await request.json()
    pattern = str((data or {}).get("pattern", "")).strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    try:
        from security.policies.safety_store import remove_protected_path
        result = remove_protected_path(pattern)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: remove protected path failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid protected path"])))
    return result


@app.post("/api/safety/protected-paths/test")
async def safety_test_path(request: Request):
    data = await request.json()
    path = str((data or {}).get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        from security.policies.safety_store import test_path
        return test_path(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: test path failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/protected-paths/reset")
async def safety_reset_protected_paths(request: Request):
    data = await request.json()
    confirm = bool((data or {}).get("confirm", False))
    if not confirm:
        raise HTTPException(status_code=400, detail="Reset requires confirm: true")
    try:
        from security.policies.safety_store import reset_protected_paths
        return reset_protected_paths()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: reset protected paths failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/temp-permissions")
async def safety_temp_permissions():
    try:
        from security.policies.safety_store import list_temp_permissions
        return {"permissions": list_temp_permissions()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: temp permissions failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/temp-permissions")
async def safety_add_temp_permission(request: Request):
    data = await request.json()
    try:
        from security.policies.safety_store import add_temp_permission
        result = add_temp_permission(data or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: add temp permission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid temp permission"])))
    return result


@app.post("/api/safety/temp-permissions/revoke")
async def safety_revoke_temp_permission(request: Request):
    data = await request.json()
    permission_id = str((data or {}).get("id", "")).strip()
    if not permission_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        from security.policies.safety_store import revoke_temp_permission
        return revoke_temp_permission(permission_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: revoke temp permission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/temp-permissions/extend")
async def safety_extend_temp_permission(request: Request):
    data = await request.json()
    permission_id = str((data or {}).get("id", "")).strip()
    seconds = int((data or {}).get("seconds", 3600) or 3600)
    if not permission_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        from security.policies.safety_store import extend_temp_permission
        result = extend_temp_permission(permission_id, seconds)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: extend temp permission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid temp permission"])))
    return result


@app.post("/api/safety/temp-permissions/convert")
async def safety_convert_temp_permission(request: Request):
    data = await request.json()
    permission_id = str((data or {}).get("id", "")).strip()
    if not permission_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        from security.policies.safety_store import convert_temp_permission
        result = convert_temp_permission(permission_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: convert temp permission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid temp permission"])))
    return result


@app.get("/api/safety/approvals")
async def safety_approvals():
    try:
        from security.policies.safety_store import list_approvals
        return {"approvals": list_approvals()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: approvals failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/approvals/revoke")
async def safety_revoke_approval(request: Request):
    data = await request.json()
    approval_id = str((data or {}).get("id", "")).strip()
    if not approval_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        from security.policies.safety_store import revoke_approval
        result = revoke_approval(approval_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: revoke approval failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid approval"])))
    return result


@app.post("/api/safety/approvals/clear")
async def safety_clear_approvals(request: Request):
    data = await request.json()
    confirm = bool((data or {}).get("confirm", False))
    if not confirm:
        raise HTTPException(status_code=400, detail="Clear requires confirm: true")
    try:
        from security.policies.safety_store import clear_expired_approvals
        return clear_expired_approvals()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: clear approvals failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/events")
async def safety_events():
    try:
        from security.policies.safety_store import list_events
        return {"events": list_events(limit=200)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: events failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/diagnostics")
async def safety_diagnostics():
    try:
        from security.policies.safety_store import run_diagnostics
        return run_diagnostics()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: diagnostics failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.get("/api/safety/presets")
async def safety_presets():
    try:
        from security.policies.safety_store import list_presets
        return {"presets": list_presets()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: presets failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")


@app.post("/api/safety/presets/apply")
async def safety_apply_preset(request: Request):
    data = await request.json()
    preset_id = str((data or {}).get("preset", "")).strip()
    if not preset_id:
        raise HTTPException(status_code=400, detail="preset is required")
    try:
        from security.policies.safety_store import apply_preset
        result = apply_preset(preset_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("safety: apply preset failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Safety store is unavailable")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="; ".join(result.get("errors", ["Invalid preset"])))
    if preset_id != "custom" and result.get("changes"):
        _safety_apply_runtime()
    return result


@app.post("/api/add-dir")
async def add_working_dir(request: Request):
    """Add an extra local directory to the active runtime context."""
    data = await request.json()
    raw_path = str(data.get("path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="path is required")
    # Validate and canonicalize exactly like /api/workspace/dirs so symlink
    # escapes, network paths, and in-workspace duplicates are rejected.
    validation = _validate_workspace_path(raw_path)
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("reason", "Invalid directory"))
    target = validation["path"]
    root = _workspace_root()
    if target == root or _is_within(root, target):
        raise HTTPException(status_code=400, detail="Path is inside the workspace root and does not need to be added")
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail=f"Directory not found: {target}")
    dirs = _RUNTIME_SETTINGS.setdefault("additional_dirs", [])
    if target in dirs:
        raise HTTPException(status_code=409, detail="Directory is already added")
    for existing in dirs:
        if _is_within(existing, target) or _is_within(target, existing):
            raise HTTPException(status_code=409, detail=f"Directory overlaps an existing additional directory: {existing}")
    dirs.append(target)
    apply_runtime_to_all_loops()
    return {"status": "success", "path": target, "additional_dirs": dirs}


def _open_path_sync(target: str) -> None:
    """Launch the local file manager without touching async request state."""
    import subprocess
    if os.name == "nt":
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


@app.post("/api/open")
async def open_path(request: Request):
    """Open a file or folder in the OS file manager (best-effort, local only)."""
    data = await request.json()
    raw_path = str(data.get("path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="path is required")
    target = os.path.realpath(os.path.abspath(raw_path))
    project_root_real = os.path.realpath(os.path.abspath(_PROJECT_ROOT))
    try:
        inside = os.path.commonpath([project_root_real, target]) == project_root_real
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=403, detail="Opening paths outside the project is not allowed")
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Path not found")
    try:
        await asyncio.to_thread(_open_path_sync, target)
        return {"status": "success", "path": target}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open path: {exc}")


@app.post("/api/run")
async def execute_bash_command(request: Request):
    """Run a command through the canonical risk scorer and sandbox."""
    data = await request.json()
    command = str(data.get("command", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="No command provided")

    from sandbox.risk import CommandRiskScorer
    from sandbox.sandbox_manager import SovereignSandbox
    assessment = CommandRiskScorer().assess(command)
    if (
        os.environ.get("NEXUS_ALLOW_DANGEROUS_SHELL", "false").lower() != "true"
        and assessment
        and assessment.blocked
    ):
        raise HTTPException(status_code=403, detail=f"Command blocked by risk policy: {assessment.summary()}")
    try:
        root = _workspace_root()
        sandbox = SovereignSandbox(root)
        output = await asyncio.to_thread(sandbox.execute, command, root)
        returncode = sandbox.last_exit_code if sandbox.last_exit_code is not None else 0
        return {
            "command": command,
            "returncode": returncode,
            "output": output[:5000],
            "error": None if returncode == 0 else output[:2000],
        }
    except Exception as e:
        return {
            "command": command,
            "returncode": -1,
            "output": "",
            "error": _public_api_failure("Sandbox command execution", e),
        }


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


# ── Workspace API ─────────────────────────────────────────────────────────────

_WORKSPACE_ACTIVITY_LOCK = threading.RLock()
_WORKSPACE_ACTIVITY: deque = deque(maxlen=200)
_WORKSPACE_DIR_ACCESS: Dict[str, str] = {}
_WORKSPACE_SCAN_LOCK = threading.RLock()
_WORKSPACE_SCAN_STATE: Dict[str, Any] = {"status": "not_started", "started_at": 0.0, "finished_at": 0.0, "progress": 0.0, "current_file": "", "indexed": 0, "failed": 0, "skipped": 0, "message": ""}
_WORKSPACE_INDEX_LOCK = threading.Lock()
_WORKSPACE_SUMMARY_CACHE_LOCK = threading.RLock()
_WORKSPACE_SUMMARY_CACHE: Dict[str, Any] = {"computed_at": 0.0, "root": None, "payload": None, "warming": False}
_WORKSPACE_SUMMARY_TTL = 300.0


def _invalidate_workspace_summary_cache() -> None:
    with _WORKSPACE_SUMMARY_CACHE_LOCK:
        _WORKSPACE_SUMMARY_CACHE["computed_at"] = 0.0
        _WORKSPACE_SUMMARY_CACHE["payload"] = None


def _workspace_summary_snapshot_path() -> str:
    return os.path.join(_PROJECT_ROOT, ".cache", "workspace_summary.json")


def _save_workspace_summary_snapshot(payload: Dict[str, Any], root: str) -> None:
    """Persist the computed summary to disk so restarts never re-scan slowly."""
    try:
        path = _workspace_summary_snapshot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"root": root, "saved_at": time.time(), "payload": payload}, f, ensure_ascii=False)
    except OSError:
        logger.warning("Could not persist workspace summary snapshot", exc_info=True)


def _load_workspace_summary_snapshot(root: str) -> Optional[Dict[str, Any]]:
    """Load a previously persisted summary for this root, or None."""
    try:
        path = _workspace_summary_snapshot_path()
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("root") != root or not isinstance(data.get("payload"), dict):
            return None
        return data["payload"]
    except (OSError, ValueError):
        return None


def _refresh_workspace_summary(root: str) -> Dict[str, Any]:
    """Compute the full summary, keep it in memory, and persist it to disk."""
    payload = _compute_workspace_summary(root)
    with _WORKSPACE_SUMMARY_CACHE_LOCK:
        _WORKSPACE_SUMMARY_CACHE.update({"computed_at": time.time(), "root": root, "payload": payload, "warming": False})
    _save_workspace_summary_snapshot(payload, root)
    return payload


def _warm_workspace_summary() -> None:
    """Compute the summary in the background at server startup so first loads are instant."""
    def worker() -> None:
        try:
            _refresh_workspace_summary(_workspace_root())
        except Exception:
            logger.warning("Workspace summary warm-up failed", exc_info=True)
    threading.Thread(target=worker, daemon=True).start()


def _ensure_workspace_summary_refresh(root: str) -> None:
    """Kick a background refresh unless one is already running (no duplicate threads)."""
    with _WORKSPACE_SUMMARY_CACHE_LOCK:
        if _WORKSPACE_SUMMARY_CACHE.get("warming"):
            return
        _WORKSPACE_SUMMARY_CACHE["warming"] = True

    def worker() -> None:
        try:
            _refresh_workspace_summary(root)
        except Exception:
            logger.warning("Workspace summary background refresh failed", exc_info=True)
        finally:
            # A failure must not wedge the cache in "warming" forever, or every
            # later cold start busy-waits the full refresh loop.
            with _WORKSPACE_SUMMARY_CACHE_LOCK:
                _WORKSPACE_SUMMARY_CACHE["warming"] = False
    threading.Thread(target=worker, daemon=True).start()


def _workspace_root() -> str:
    configured = str(_RUNTIME_SETTINGS.get("workspace_root") or "").strip()
    if configured:
        return os.path.realpath(os.path.abspath(configured))
    # Default to workspace/ subfolder if it exists, otherwise project root
    workspace_dir = os.path.join(_PROJECT_ROOT, "workspace")
    return os.path.realpath(workspace_dir if os.path.isdir(workspace_dir) else _PROJECT_ROOT)


def _canonical_workspace_path(raw: str) -> str:
    raw = str(raw or "").strip().strip('"').strip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")
    if not os.path.isabs(raw):
        raw = os.path.join(_workspace_root(), raw)
    # Canonicalize existing symlinks/junctions before any containment check.
    # ``abspath`` alone is insufficient on Windows, where a junction can
    # redirect a seemingly-in-root path to another volume.
    raw = os.path.realpath(os.path.abspath(os.path.normpath(raw)))
    if os.name == "nt":
        is_drive = len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"
        is_unc = raw.startswith("\\\\")
        if not is_drive and not is_unc:
            raise HTTPException(status_code=400, detail="Unsupported path (network or device paths are not accepted)")
    return raw


def _is_within(parent: str, child: str) -> bool:
    try:
        parent_norm = os.path.normcase(os.path.realpath(os.path.abspath(parent)))
        child_norm = os.path.normcase(os.path.realpath(os.path.abspath(child)))
        return os.path.commonpath([parent_norm, child_norm]) == parent_norm
    except Exception:
        return False


def _validate_workspace_path(raw: str) -> Dict[str, Any]:
    """Validate a candidate workspace root or additional directory.

    Returns a dict with validity, reason, canonical path, and permission flags.
    Never trusts client-reported permissions — these are checked on disk.
    """
    try:
        target = _canonical_workspace_path(raw)
    except HTTPException as exc:
        return {"valid": False, "reason": exc.detail, "path": str(raw or "").strip()}
    if not os.path.exists(target):
        return {"valid": False, "reason": "Path does not exist on disk", "path": target, "exists": False}
    if not os.path.isdir(target):
        return {"valid": False, "reason": "Path is a file — a directory is required", "path": target, "exists": True, "is_dir": False}
    readable = os.access(target, os.R_OK)
    writable = os.access(target, os.W_OK)
    if not readable and not writable:
        return {"valid": False, "reason": "Permission denied: no read or write access", "path": target, "exists": True, "is_dir": True, "readable": False, "writable": False}
    return {
        "valid": True,
        "path": target,
        "exists": True,
        "is_dir": True,
        "readable": readable,
        "writable": writable,
        "reason": "ok",
    }


def _record_workspace_activity(event_type: str, description: str, status: str = "ok", details: Any = None) -> None:
    with _WORKSPACE_ACTIVITY_LOCK:
        _WORKSPACE_ACTIVITY.appendleft({
            "timestamp": time.time(),
            "event_type": event_type,
            "description": description,
            "status": status,
            "details": details,
        })


def _git_summary(root: str) -> Dict[str, Any]:
    import subprocess
    def run(args: List[str], timeout: int = 3) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout, errors="replace")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return subprocess.CompletedProcess(args, 1, "", str(exc))

    top = run(["git", "rev-parse", "--show-toplevel"])
    if top.returncode != 0 or not top.stdout.strip():
        return {"available": bool(shutil.which("git")), "is_repo": False}
    repo_root = top.stdout.strip()
    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    upstream = ""
    upstream_raw = run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"]).stdout.strip()
    if upstream_raw and upstream_raw != "@{upstream}":
        upstream = upstream_raw
    changed = staged = untracked = 0
    porcelain = run(["git", "status", "--porcelain=v1"])
    for line in porcelain.stdout.splitlines():
        if line.startswith("??"):
            untracked += 1
            continue
        if len(line) > 1 and line[0] != " ":
            staged += 1
        if len(line) > 1 and line[1] != " ":
            changed += 1
    last_commit = ""
    log = run(["git", "log", "-1", "--format=%h %s"])
    if log.returncode == 0 and log.stdout.strip():
        last_commit = log.stdout.strip()
    return {
        "available": bool(shutil.which("git")),
        "is_repo": True,
        "root": repo_root,
        "branch": branch or "unknown",
        "upstream": upstream,
        "changed_files": changed,
        "staged_files": staged,
        "untracked_files": untracked,
        "last_commit": last_commit,
    }


_DEFAULT_IGNORE_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build", "coverage", ".next", ".cache", ".pytest_cache", ".mypy_cache"}
_DEFAULT_IGNORE_FILES = {"*.pyc", "*.pyo", ".DS_Store", "*.log"}
_BINARY_EXTENSIONS = {
    "images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg", ".tiff", ".avif", ".heic"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma"},
    "video": {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv"},
    "archives": {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz"},
    "executables": {".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".apk", ".app", ".class", ".o", ".obj", ".jar", ".pyc"},
    "office": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf"},
}
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".rs", ".go", ".rb", ".php",
    ".swift", ".kt", ".kts", ".scala", ".sh", ".ps1", ".bat", ".cmd", ".sql", ".html", ".css", ".scss", ".less",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".conf", ".vue", ".svelte", ".lua", ".pl", ".r",
    ".m", ".ipynb", ".dart", ".ex", ".exs", ".clj", ".ml", ".fs", ".hs", ".zig",
}
_DOC_EXTENSIONS = {".md", ".markdown", ".txt", ".rst", ".adoc", ".tex", ".pdf"}


def _gitignore_rules(root: str) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for source in (".gitignore", ".nexusignore"):
        path = os.path.join(root, source)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    rules.append({"pattern": stripped, "source": source, "kind": "ignore", "negated": stripped.startswith("!")})
        except OSError:
            continue
    for name in sorted(_DEFAULT_IGNORE_DIRS):
        rules.append({"pattern": name, "source": "built-in", "kind": "ignore", "negated": False})
    for pat in sorted(_DEFAULT_IGNORE_FILES):
        rules.append({"pattern": pat, "source": "built-in", "kind": "ignore", "negated": False})
    return rules


def _path_is_ignored(rel_path: str, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Test a relative path against rules in order (last matching rule wins, like git)."""
    rel = rel_path.replace("\\", "/")
    result: Dict[str, Any] = {"ignored": False, "matched": None, "source": None}
    for rule in rules:
        pattern = rule["pattern"]
        matched = False
        try:
            if not rule.get("negated"):
                import fnmatch
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
                    matched = True
                elif "/" in pattern:
                    matched = fnmatch.fnmatch(rel, pattern.rstrip("/") + "/*") or rel.startswith(pattern.rstrip("/") + "/")
                else:
                    matched = rel == pattern or rel.startswith(pattern + "/")
        except Exception:
            continue
        if matched:
            result["ignored"] = not rule.get("negated")
            result["matched"] = rule["pattern"]
            result["source"] = rule["source"]
    return result


def _scan_workspace_stats(root: str) -> Dict[str, Any]:
    rules = _gitignore_rules(root)
    stats = {
        "files": 0, "folders": 0, "indexed_files": 0, "ignored_files": 0, "failed_files": 0,
        "source_files": 0, "documentation_files": 0, "binary_files": 0, "total_size": 0,
        "indexed_text_size": 0, "languages": {}, "calculated_at": time.time(),
    }
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        pruned = []
        for d in dirnames:
            if d in _DEFAULT_IGNORE_DIRS or d.startswith("."):
                pruned.append(d)
            else:
                rel_dir = os.path.relpath(os.path.join(dirpath, d), root).replace("\\", "/")
                if _path_is_ignored(rel_dir, rules).get("ignored"):
                    pruned.append(d)
        dirnames[:] = [d for d in dirnames if d not in pruned]
        stats["folders"] += 1
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            try:
                rel = os.path.relpath(full, root).replace("\\", "/")
            except (ValueError, OSError):
                stats["failed_files"] += 1
                continue
            if _path_is_ignored(rel, rules).get("ignored"):
                stats["ignored_files"] += 1
                continue
            try:
                size = os.path.getsize(full)
                stats["total_size"] += size
            except OSError:
                stats["failed_files"] += 1
                continue
            ext = os.path.splitext(fname)[1].lower()
            stats["files"] += 1
            if ext in _SOURCE_EXTENSIONS:
                stats["source_files"] += 1
                stats["indexed_files"] += 1
                stats["indexed_text_size"] += size
                lang = ext.lstrip(".") or "text"
                stats["languages"][lang] = stats["languages"].get(lang, 0) + 1
            elif ext in _DOC_EXTENSIONS:
                stats["documentation_files"] += 1
                stats["indexed_files"] += 1
                stats["indexed_text_size"] += size
            elif any(ext in group for group in _BINARY_EXTENSIONS.values()):
                stats["binary_files"] += 1
            else:
                stats["indexed_files"] += 1
                stats["indexed_text_size"] += size
    return stats


def _detect_project(root: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": os.path.basename(root),
        "type": "unknown",
        "languages": [],
        "frameworks": [],
        "package_manager": None,
        "build_command": None,
        "dev_command": None,
        "test_command": None,
        "lint_command": None,
        "format_command": None,
        "entry_points": [],
        "manifests": [],
        "lock_files": [],
        "config_files": [],
        "detected_at": time.time(),
    }
    try:
        entries = os.listdir(root)
    except OSError:
        return result
    for name in entries:
        full = os.path.join(root, name)
        if os.path.isfile(full):
            result["manifests"].append(name)
            result["config_files"].append(name)
    if "package.json" in result["manifests"]:
        result["type"] = "node"
        result["package_manager"] = "npm"
        result["languages"].extend(["JavaScript", "TypeScript"])
        try:
            with open(os.path.join(root, "package.json"), "r", encoding="utf-8") as f:
                pkg = json.load(f)
            result["name"] = pkg.get("name", result["name"])
            scripts = pkg.get("scripts") or {}
            result["build_command"] = scripts.get("build") or scripts.get("compile")
            result["dev_command"] = scripts.get("dev") or scripts.get("start")
            result["test_command"] = scripts.get("test")
            result["lint_command"] = scripts.get("lint")
            result["format_command"] = scripts.get("format")
        except (OSError, ValueError):
            pass
    if "pyproject.toml" in result["manifests"]:
        result["type"] = "python"
        result["package_manager"] = "pdm" if os.path.isfile(os.path.join(root, "pdm.lock")) else ("poetry" if os.path.isfile(os.path.join(root, "poetry.lock")) else "pip")
        result["languages"].append("Python")
        result["test_command"] = "python -m pytest"
        result["build_command"] = None
    elif "requirements.txt" in result["manifests"]:
        result["type"] = "python"
        result["package_manager"] = "pip"
        result["languages"].append("Python")
    if "Cargo.toml" in result["manifests"]:
        result["type"] = "rust"
        result["package_manager"] = "cargo"
        result["languages"].append("Rust")
        result["build_command"] = "cargo build"
        result["test_command"] = "cargo test"
    if "go.mod" in result["manifests"]:
        result["type"] = "go"
        result["package_manager"] = "go modules"
        result["languages"].append("Go")
        result["test_command"] = "go test ./..."
    if any(lock in result["manifests"] for lock in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")):
        if "package-lock.json" in result["manifests"]:
            result["package_manager"] = "npm"
        elif "yarn.lock" in result["manifests"]:
            result["package_manager"] = "yarn"
        else:
            result["package_manager"] = "pnpm"
    if "README.md" in result["manifests"]:
        result["documentation"] = ["README.md"]
    if not result["languages"]:
        result["languages"] = ["unknown"]
    result["languages"] = sorted(set(result["languages"]))
    return result


_DEFAULT_PROTECTED_PATTERNS = [
    {"pattern": ".git/**", "reason": "Git internals", "policy": "deny", "scope": "global", "mandatory": True},
    {"pattern": ".env", "reason": "Environment secrets", "policy": "warn", "scope": "global", "mandatory": True},
    {"pattern": ".env.*", "reason": "Environment secrets", "policy": "warn", "scope": "global", "mandatory": True},
    {"pattern": "**/*.pem", "reason": "Private keys", "policy": "warn", "scope": "global", "mandatory": True},
    {"pattern": "**/*.key", "reason": "Private keys", "policy": "warn", "scope": "global", "mandatory": True},
    {"pattern": "**/.ssh/**", "reason": "SSH credentials", "policy": "deny", "scope": "global", "mandatory": True},
    {"pattern": "**/*credential*", "reason": "Credentials", "policy": "warn", "scope": "global", "mandatory": True},
    {"pattern": "**/*secret*", "reason": "Secrets", "policy": "warn", "scope": "global", "mandatory": True},
]


def _protected_paths() -> List[Dict[str, Any]]:
    paths = [dict(entry) for entry in _DEFAULT_PROTECTED_PATTERNS]
    try:
        config = _load_nexus_config()
        workspace_cfg = config.get("workspace") if isinstance(config.get("workspace"), dict) else {}
        user = workspace_cfg.get("protected_paths") or []
        if isinstance(user, list):
            for entry in user:
                if isinstance(entry, dict):
                    paths.append({**entry, "scope": "workspace", "mandatory": False})
                else:
                    paths.append({"pattern": str(entry), "reason": "User configured", "policy": "warn", "scope": "workspace", "mandatory": False})
    except Exception:
        pass
    return paths


def _index_status() -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "status": "not_started",
        "indexed_files": 0,
        "total_chunks": 0,
        "index_storage_size": 0,
        "last_full_scan": None,
        "last_incremental_scan": None,
        "current_file": "",
        "recent_errors": [],
    }
    try:
        rag_index = os.path.join(_PROJECT_ROOT, "knowledge", "_rag_index.json")
        if os.path.isfile(rag_index):
            try:
                with open(rag_index, "r", encoding="utf-8") as f:
                    data = json.load(f)
                docs = data if isinstance(data, list) else (data.get("documents") if isinstance(data, dict) else None)
                if isinstance(docs, list):
                    status["indexed_files"] = len(docs)
                    status["total_chunks"] = sum(len(d.get("chunks") or []) if isinstance(d, dict) else 0 for d in docs)
                status["index_storage_size"] = os.path.getsize(rag_index)
                status["last_full_scan"] = data.get("updated_at") if isinstance(data, dict) else None
            except (OSError, ValueError):
                pass
            status["status"] = "ready"
    except Exception:
        pass
    scan = dict(_WORKSPACE_SCAN_STATE)
    if scan.get("status") in {"scanning", "parsing"}:
        status["status"] = scan["status"]
        status["current_file"] = scan.get("current_file") or ""
    if _WORKSPACE_SCAN_STATE.get("finished_at"):
        status["last_full_scan"] = status.get("last_full_scan") or _WORKSPACE_SCAN_STATE["finished_at"]
    return status


def _storage_stats() -> Dict[str, Any]:
    def dir_size(path: str) -> int:
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for fname in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        continue
        except OSError:
            pass
        return total

    sessions = os.path.join(_PROJECT_ROOT, "logs", "sessions")
    work_events = os.path.join(_PROJECT_ROOT, "workspace", "work_events")
    knowledge = os.path.join(_PROJECT_ROOT, "knowledge")
    cache = os.path.join(_PROJECT_ROOT, ".cache")
    return {
        "session_count": len(_LOOPS),
        "session_storage_size": dir_size(sessions),
        "cache_size": dir_size(cache),
        "index_size": dir_size(knowledge),
        "temp_size": dir_size(os.path.join(_PROJECT_ROOT, "tmp")),
        "work_event_count": _WORK_EVENT_MAX_RECORDS,
    }


def _workspace_health(root: str, git: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    exists = os.path.isdir(root)
    add("Root exists", "healthy" if exists else "failed", "Directory is present on disk" if exists else "Directory is missing")
    readable = exists and os.access(root, os.R_OK)
    add("Root readable", "healthy" if readable else "failed", "Read access verified" if readable else "No read permission")
    writable = exists and os.access(root, os.W_OK)
    add("Root writable", "healthy" if writable else "warning", "Write access verified" if writable else "No write permission (read-only workspace)")

    rules = _gitignore_rules(root)
    import fnmatch
    long_paths = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                if len(full) > 250:
                    long_paths += 1
                if long_paths > 5:
                    break
            if long_paths > 5:
                break
    except OSError:
        pass
    add("Windows path-length risk", "warning" if long_paths else "healthy", f"{long_paths} path(s) exceed 250 characters" if long_paths else "No long paths detected")

    try:
        usage = shutil.disk_usage(root)
        free_gb = usage.free / (1024 ** 3)
        add("Disk space", "warning" if free_gb < 1 else "healthy", f"{free_gb:.1f} GB free")
    except OSError:
        add("Disk space", "not_checked", "Could not query disk usage")

    git = git if git is not None else _git_summary(root)
    add("Git availability", "healthy" if git.get("is_repo") else "not_checked" if git.get("available") else "unsupported", "Repository detected" if git.get("is_repo") else "Git installed" if git.get("available") else "Git not installed or not on PATH")

    try:
        import fnmatch
        env_files = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith(".env") or fname.endswith(".pem") or fname.endswith(".key"):
                    env_files += 1
        add("Sensitive-file presence", "warning" if env_files else "healthy", f"{env_files} sensitive file(s) found" if env_files else "No sensitive files detected")
    except OSError:
        add("Sensitive-file presence", "not_checked", "Could not scan")

    index = _index_status()
    add("Index health", "healthy" if index.get("status") in {"ready", "not_started"} else "warning", f"Index status: {index.get('status')}")
    add("Backend connection", "healthy", "Connected to Nexus server")
    return checks


def _workspace_instructions() -> Dict[str, Any]:
    try:
        config = _load_nexus_config()
        ws = config.get("workspace") if isinstance(config.get("workspace"), dict) else {}
        instructions = ws.get("instructions") or ""
        return {
            "instructions": str(instructions),
            "active": bool(instructions),
            "updated_at": ws.get("instructions_updated_at"),
        }
    except Exception:
        return {"instructions": "", "active": False, "updated_at": None}


def _workspace_memory_meta() -> Dict[str, Any]:
    try:
        from memory import MemoryManager
        mem = MemoryManager()
        entries = getattr(mem, "store", None)
        count = len(entries) if isinstance(entries, (list, dict)) else 0
        size = 0
        store_path = getattr(mem, "store_path", None) or getattr(mem, "memory_path", None)
        if store_path and os.path.isfile(str(store_path)):
            size = os.path.getsize(str(store_path))
        return {"enabled": True, "entry_count": count, "storage_size": size, "last_update": getattr(mem, "last_update", None), "last_retrieval": getattr(mem, "last_retrieval", None), "scope": "workspace"}
    except Exception:
        return {"enabled": False, "entry_count": 0, "storage_size": 0, "last_update": None, "last_retrieval": None, "scope": "workspace", "unavailable_reason": "Memory manager is not available in this runtime"}


def _workspace_export() -> Dict[str, Any]:
    try:
        config = _load_nexus_config()
        workspace_cfg = config.get("workspace") if isinstance(config.get("workspace"), dict) else {}
    except Exception:
        workspace_cfg = {}
    root = _workspace_root()
    git = _git_summary(root)
    return {
        "format": "nexus-workspace-config",
        "version": 1,
        "exported_at": time.time(),
        "workspace": {
            "root": _RUNTIME_SETTINGS.get("workspace_root") or "",
            "additional_dirs": _RUNTIME_SETTINGS.get("additional_dirs") or [],
            "directory_access": _WORKSPACE_DIR_ACCESS,
            "instructions": workspace_cfg.get("instructions") or "",
            "protected_paths": [p for p in workspace_cfg.get("protected_paths") or [] if isinstance(p, dict)] if isinstance(workspace_cfg.get("protected_paths"), list) else [],
            "ignore_rules": workspace_cfg.get("ignore_rules") or [],
            "memory": workspace_cfg.get("memory") or {},
        },
        "git": {"is_repo": git.get("is_repo", False), "branch": git.get("branch"), "root": git.get("root")} if git.get("is_repo") else None,
    }


def _workspace_dirs_detail() -> List[Dict[str, Any]]:
    root = _workspace_root()
    result = []
    for path in _RUNTIME_SETTINGS.get("additional_dirs") or []:
        exists = os.path.isdir(path)
        entry: Dict[str, Any] = {
            "path": path,
            "name": os.path.basename(path.rstrip("\\/")) or path,
            "available": exists,
            "readable": exists and os.access(path, os.R_OK),
            "writable": exists and os.access(path, os.W_OK),
            "access_mode": _WORKSPACE_DIR_ACCESS.get(path, "read_write"),
            "index_status": "not_indexed",
            "file_count": 0,
            "last_scanned": None,
        }
        if exists:
            try:
                entry["file_count"] = sum(len(files) for _, _, files in os.walk(path))
            except OSError:
                pass
            entry["index_status"] = "ready"
        result.append(entry)
    return result


def _compute_workspace_summary(root: str) -> Dict[str, Any]:
    """Build the full workspace summary. Expensive (~7-10s) — call in background only."""
    exists = os.path.isdir(root)
    state = "connected" if exists else "missing"
    if not _RUNTIME_SETTINGS.get("workspace_root"):
        state = "connected" if os.path.isdir(_PROJECT_ROOT) else "not_configured"
    git = _git_summary(root)
    stats = _scan_workspace_stats(root) if exists else None
    project = _detect_project(root) if exists else None
    dirs = _workspace_dirs_detail()
    return {
        "status": "success",
        "root": root,
        "workspace_name": os.path.basename(root.rstrip("\\/")) or root,
        "state": state,
        "exists": exists,
        "readable": exists and os.access(root, os.R_OK),
        "writable": exists and os.access(root, os.W_OK),
        "root_protection": True,
        "read_permission": "read" if exists and os.access(root, os.R_OK) else "denied",
        "write_permission": "write" if exists and os.access(root, os.W_OK) else "read_only",
        "configured_root": _RUNTIME_SETTINGS.get("workspace_root") or "",
        "is_repo": git.get("is_repo", False),
        "git_branch": git.get("branch"),
        "last_scanned": stats.get("calculated_at") if stats else None,
        "file_count": stats.get("files", 0) if stats else 0,
        "folder_count": stats.get("folders", 0) if stats else 0,
        "indexed_file_count": stats.get("indexed_files", 0) if stats else 0,
        "indexed_text_size": stats.get("indexed_text_size", 0) if stats else 0,
        "additional_directory_count": len(dirs),
        "languages": (project or {}).get("languages") or (sorted((stats or {}).get("languages", {}).keys()) if stats else []),
        "project_type": (project or {}).get("type", "unknown"),
        "project_name": (project or {}).get("name") or os.path.basename(root.rstrip("\\/")) or root,
        "additional_dirs": dirs,
        "session_count": len(_LOOPS),
        "index": _index_status(),
        "health": _workspace_health(root, git),
    }


@app.get("/api/workspace")
def workspace_summary():
    """Full workspace summary for the Settings → Workspace page. Instant: served from
    memory cache or the persisted disk snapshot; never blocks on a full re-scan."""
    root = _workspace_root()
    with _WORKSPACE_SUMMARY_CACHE_LOCK:
        cached = _WORKSPACE_SUMMARY_CACHE
        if (
            cached.get("payload") is not None
            and cached.get("root") == root
            and time.time() - cached.get("computed_at", 0.0) < _WORKSPACE_SUMMARY_TTL
        ):
            return cached["payload"]
    snapshot = _load_workspace_summary_snapshot(root)
    if snapshot is not None:
        _ensure_workspace_summary_refresh(root)
        return snapshot
    # True cold start (no snapshot yet). Kick a background compute if one is not
    # already running, then wait for it so we never duplicate the full scan.
    _ensure_workspace_summary_refresh(root)
    deadline = time.time() + 60.0
    while time.time() < deadline:
        with _WORKSPACE_SUMMARY_CACHE_LOCK:
            cached = _WORKSPACE_SUMMARY_CACHE
            if cached.get("payload") is not None and cached.get("root") == root:
                return cached["payload"]
            if not cached.get("warming"):
                break
        time.sleep(0.25)
    return _refresh_workspace_summary(root)


@app.get("/api/workspace/git")
def workspace_git():
    return {"status": "success", **(_git_summary(_workspace_root()))}


@app.get("/api/workspace/stats")
def workspace_stats():
    return {"status": "success", "stats": _scan_workspace_stats(_workspace_root())}


@app.get("/api/workspace/project")
def workspace_project():
    return {"status": "success", "project": _detect_project(_workspace_root())}


@app.get("/api/workspace/index")
def workspace_index_status():
    return {"status": "success", **_index_status()}


@app.post("/api/workspace/index/rebuild")
def workspace_index_rebuild():
    # Check-and-set must be atomic: this is a sync threadpool handler, so two
    # concurrent requests can both observe "not scanning" and start two walks.
    with _WORKSPACE_INDEX_LOCK:
        if _WORKSPACE_SCAN_STATE.get("status") == "scanning":
            raise HTTPException(status_code=409, detail="An indexing job is already running")
        _WORKSPACE_SCAN_STATE.update({"status": "scanning", "started_at": time.time(), "progress": 0.0, "current_file": "", "indexed": 0, "skipped": 0, "failed": 0, "message": ""})
    _invalidate_workspace_summary_cache()
    root = _workspace_root()

    def _run():
        try:
            from knowledge.rag.engine import NexusAtlasRAG
            rag = NexusAtlasRAG()
            counts = {"files": 0, "failed": 0}
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if d in _DEFAULT_IGNORE_DIRS or d.startswith(".")] and [] or [d for d in dirnames if d not in _DEFAULT_IGNORE_DIRS and not d.startswith(".")]
                    for fname in filenames:
                        if os.path.splitext(fname)[1].lower() not in _SOURCE_EXTENSIONS | _DOC_EXTENSIONS:
                            _WORKSPACE_SCAN_STATE["skipped"] = _WORKSPACE_SCAN_STATE.get("skipped", 0) + 1
                            continue
                        full = os.path.join(dirpath, fname)
                        _WORKSPACE_SCAN_STATE["current_file"] = full
                        try:
                            with open(full, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read()
                            rag.store_document(os.path.relpath(full, root), content, os.path.getmtime(full))
                            counts["files"] += 1
                            _WORKSPACE_SCAN_STATE["indexed"] = counts["files"]
                        except (OSError, UnicodeDecodeError):
                            counts["failed"] += 1
                            _WORKSPACE_SCAN_STATE["failed"] = counts["failed"]
                    _WORKSPACE_SCAN_STATE["progress"] = min(1.0, (counts["files"] + 1) / max(1, counts["files"] + counts["failed"] + 1))
            except Exception as exc:
                _WORKSPACE_SCAN_STATE["message"] = str(exc)
        except Exception as exc:
            _WORKSPACE_SCAN_STATE["message"] = str(exc)
        _WORKSPACE_SCAN_STATE["finished_at"] = time.time()
        _WORKSPACE_SCAN_STATE["status"] = "ready"
        _WORKSPACE_SCAN_STATE["current_file"] = ""
        _record_workspace_activity("index_rebuilt", f"Index rebuilt ({_WORKSPACE_SCAN_STATE.get('indexed', 0)} files)", status="ok")

    threading.Thread(target=_run, daemon=True).start()
    _record_workspace_activity("index_rebuilt", "Index rebuild started", status="ok")
    return {"status": "success", "message": "Index rebuild started"}


@app.post("/api/workspace/index/clear")
def workspace_index_clear():
    try:
        rag_index = os.path.join(_PROJECT_ROOT, "knowledge", "_rag_index.json")
        if os.path.isfile(rag_index):
            os.remove(rag_index)
        _invalidate_workspace_summary_cache()
        _record_workspace_activity("index_cleared", "Index cleared", status="ok")
        return {"status": "success", "message": "Index cleared"}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not clear index: {exc}")


@app.get("/api/workspace/ignore")
def workspace_ignore_rules():
    return {"status": "success", "rules": _gitignore_rules(_workspace_root())}


@app.post("/api/workspace/ignore/test")
async def workspace_ignore_test(request: Request):
    data = await request.json()
    rel = str(data.get("path", "")).strip()
    if not rel:
        raise HTTPException(status_code=400, detail="path is required")
    _invalidate_workspace_summary_cache()
    root = _workspace_root()
    rules = _gitignore_rules(root)
    abs_path = os.path.abspath(os.path.join(root, rel)) if not os.path.isabs(rel) else os.path.abspath(rel)
    if not _is_within(root, abs_path):
        raise HTTPException(status_code=400, detail="Path is outside the workspace root")
    rel_norm = os.path.relpath(abs_path, root).replace("\\", "/")
    status = _path_is_ignored(rel_norm, rules)
    if not os.path.exists(abs_path):
        status["existence"] = "missing"
    elif os.path.isdir(abs_path):
        status["existence"] = "directory"
    else:
        status["existence"] = "file"
    status["path"] = rel_norm
    return {"status": "success", "result": status}


@app.get("/api/workspace/protected")
def workspace_protected():
    root = _workspace_root()
    entries = []
    for entry in _protected_paths():
        pattern = entry.get("pattern") or ""
        cleaned = pattern.replace("**/", "").replace("/*", "")
        candidate = os.path.join(root, cleaned) if not os.path.isabs(cleaned) else cleaned
        entries.append({**entry, "exists": os.path.exists(candidate)})
    return {"status": "success", "paths": entries}


@app.post("/api/workspace/protected")
async def workspace_protected_add(request: Request):
    data = await request.json()
    pattern = str(data.get("pattern", "")).strip()
    reason = str(data.get("reason", "")).strip() or "User configured"
    policy = str(data.get("policy", "warn")).strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    if policy not in {"deny", "warn", "allow"}:
        raise HTTPException(status_code=400, detail="policy must be deny, warn, or allow")
    def mutate(config):
        ws = config.setdefault("workspace", {})
        if not isinstance(ws, dict):
            ws = {}
            config["workspace"] = ws
        paths = ws.setdefault("protected_paths", [])
        if not isinstance(paths, list):
            paths = []
            ws["protected_paths"] = paths
        if any(isinstance(entry, dict) and entry.get("pattern") == pattern for entry in paths):
            return False
        paths.append({"pattern": pattern, "reason": reason, "policy": policy})
        return True

    added = await asyncio.to_thread(_mutate_nexus_config_sync, mutate)
    if not added:
        raise HTTPException(status_code=409, detail="That protected path already exists")
    _invalidate_workspace_summary_cache()
    _record_workspace_activity("protected_added", f"Protected path added: {pattern}", status="ok")
    return {"status": "success"}


@app.delete("/api/workspace/protected")
async def workspace_protected_remove(request: Request):
    pattern = str(request.query_params.get("pattern", "")).strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    def mutate(config):
        ws = config.get("workspace") if isinstance(config, dict) else None
        paths = ws.get("protected_paths") if isinstance(ws, dict) else None
        if not isinstance(paths, list):
            return False
        remaining = [p for p in paths if not (isinstance(p, dict) and p.get("pattern") == pattern)]
        if len(remaining) == len(paths):
            return False
        ws["protected_paths"] = remaining
        return True

    removed = await asyncio.to_thread(_mutate_nexus_config_sync, mutate)
    if not removed:
        return {"status": "success", "removed": False}
    _invalidate_workspace_summary_cache()
    _record_workspace_activity("protected_removed", f"Protected path removed: {pattern}", status="ok")
    return {"status": "success", "removed": True}


@app.get("/api/workspace/storage")
def workspace_storage():
    return {"status": "success", **_storage_stats()}


def _clear_workspace_storage_sync(root: str, target: str) -> int:
    """Clear only the server-owned workspace storage target."""
    if target == "sessions":
        path = os.path.join(root, "logs", "sessions")
        preserved = {"session_index.json"}
    elif target == "index":
        path = os.path.join(root, "knowledge", "_rag_index.json")
        preserved = set()
        if os.path.isfile(path):
            try:
                os.remove(path)
                return 1
            except OSError as exc:
                raise RuntimeError(f"Could not clear index: {exc}") from exc
        return 0
    else:
        path = {"temp": os.path.join(root, "tmp"), "cache": os.path.join(root, ".cache")}.get(target, "")
        preserved = set()
    if not path or not os.path.isdir(path):
        return 0
    count = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) and name not in preserved:
                os.remove(full)
                count += 1
        except OSError:
            continue
    return count


@app.post("/api/workspace/storage/clear")
async def workspace_storage_clear(request: Request):
    data = await request.json() if await _body_json(request) else {}
    target = str(data.get("target", "temp")).strip()
    root = _PROJECT_ROOT
    _invalidate_workspace_summary_cache()
    removable = {
        "temp": os.path.join(root, "tmp"),
        "cache": os.path.join(root, ".cache"),
    }
    if target == "sessions":
        count = await asyncio.to_thread(_clear_workspace_storage_sync, root, target)
        _record_workspace_activity("cache_cleared", f"Cleared {count} inactive session file(s)", status="ok")
        return {"status": "success", "removed": count, "note": "Project source files were not touched."}
    if target == "index":
        try:
            removed = await asyncio.to_thread(_clear_workspace_storage_sync, root, target)
            _record_workspace_activity("index_cleared", "Index cleared", status="ok")
            return {"status": "success", "removed": removed, "note": "Project source files were not touched."}
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"Could not clear index: {exc}")
    path = removable.get(target)
    if not path:
        raise HTTPException(status_code=400, detail="target must be temp, cache, sessions, or index")
    count = await asyncio.to_thread(_clear_workspace_storage_sync, root, target)
    _record_workspace_activity("cache_cleared", f"Cleared {count} file(s) from {target}", status="ok")
    return {"status": "success", "removed": count, "note": "Project source files were not touched."}


@app.get("/api/workspace/health")
def workspace_health():
    return {"status": "success", "checks": _workspace_health(_workspace_root())}


@app.get("/api/workspace/activity")
def workspace_activity():
    with _WORKSPACE_ACTIVITY_LOCK:
        return {"status": "success", "events": list(_WORKSPACE_ACTIVITY)}


@app.get("/api/workspace/instructions")
def workspace_instructions_get():
    return {"status": "success", **_workspace_instructions()}


@app.post("/api/workspace/instructions")
async def workspace_instructions_save(request: Request):
    data = await request.json()
    instructions = str(data.get("instructions", "")).strip()
    def mutate(config):
        ws = config.setdefault("workspace", {})
        if not isinstance(ws, dict):
            ws = {}
            config["workspace"] = ws
        ws["instructions"] = instructions
        ws["instructions_updated_at"] = time.time()

    await asyncio.to_thread(_mutate_nexus_config_sync, mutate)
    _invalidate_workspace_summary_cache()
    _record_workspace_activity("settings_changed", "Workspace instructions updated", status="ok")
    return {"status": "success"}


@app.get("/api/workspace/memory")
def workspace_memory_get():
    return {"status": "success", **_workspace_memory_meta()}


@app.post("/api/workspace/memory/clear")
def workspace_memory_clear():
    _invalidate_workspace_summary_cache()
    cleared = False
    try:
        from memory import MemoryManager
        mem = MemoryManager()
        if hasattr(mem, "clear"):
            mem.clear()
            cleared = True
    except Exception:
        pass
    _record_workspace_activity("settings_changed", "Workspace memory cleared" if cleared else "Workspace memory clear unavailable", status="ok" if cleared else "error")
    return {"status": "success" if cleared else "unsupported", "cleared": cleared, "note": "Project files were not touched."}


@app.get("/api/workspace/export")
def workspace_export():
    return {"status": "success", **_workspace_export()}


@app.post("/api/workspace/import")
async def workspace_import(request: Request):
    data = await request.json()
    payload = data.get("config") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="config object is required")
    if payload.get("format") != "nexus-workspace-config":
        raise HTTPException(status_code=400, detail="Unsupported or malformed configuration format")
    version = payload.get("version")
    if not isinstance(version, int) or version > 1:
        raise HTTPException(status_code=400, detail="Unsupported configuration version")
    ws = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    preview = {
        "instructions": bool(ws.get("instructions")),
        "protected_paths": len(ws.get("protected_paths") or []) if isinstance(ws.get("protected_paths"), list) else 0,
        "ignore_rules": len(ws.get("ignore_rules") or []) if isinstance(ws.get("ignore_rules"), list) else 0,
        "memory": len(ws.get("memory") or {}) if isinstance(ws.get("memory"), dict) else 0,
    }
    if data.get("apply"):
        def mutate(config):
            existing = config.setdefault("workspace", {})
            if not isinstance(existing, dict):
                existing = {}
                config["workspace"] = existing
            for key in ("instructions", "protected_paths", "ignore_rules", "memory"):
                if key in ws:
                    existing[key] = ws[key]

        await asyncio.to_thread(_mutate_nexus_config_sync, mutate)
        _invalidate_workspace_summary_cache()
        _record_workspace_activity("settings_changed", "Workspace configuration imported", status="ok")
        return {"status": "success", "applied": True, "preview": preview}
    return {"status": "success", "applied": False, "preview": preview}


@app.post("/api/workspace/reset")
def workspace_reset():
    """Reset workspace settings (access, instructions, protected paths, dirs). Does not delete files."""
    try:
        config = _load_nexus_config()
        config.pop("workspace", None)
        _save_nexus_config(config)
    except Exception:
        pass
    _RUNTIME_SETTINGS["additional_dirs"] = []
    _WORKSPACE_DIR_ACCESS.clear()
    _save_runtime_preferences()
    _invalidate_workspace_summary_cache()
    apply_runtime_to_all_loops()
    _record_workspace_activity("settings_changed", "Workspace settings reset to defaults", status="ok")
    return {"status": "success", "message": "Workspace settings reset. Project files were not touched."}


async def _body_json(request: Request) -> bool:
    try:
        await request.json()
        return True
    except Exception:
        return False


@app.get("/api/workspace/validate")
def workspace_validate(path: str = ""):
    """Validate a candidate workspace root or additional-directory path."""
    if not path:
        raise HTTPException(status_code=400, detail="path query parameter is required")
    return {"status": "success", "validation": _validate_workspace_path(path)}


@app.post("/api/workspace/root")
async def workspace_set_root(request: Request):
    """Switch the workspace root. Validates on disk before applying and keeps the old root on failure."""
    data = await request.json()
    raw_path = str(data.get("path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="path is required")
    old_root = _workspace_root()
    validation = _validate_workspace_path(raw_path)
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("reason", "Invalid workspace path"))
    _RUNTIME_SETTINGS["workspace_root"] = validation["path"]
    await asyncio.to_thread(_save_runtime_preferences)
    _invalidate_workspace_summary_cache()
    apply_runtime_to_all_loops()
    _record_workspace_activity("root_changed", f"Workspace root changed to {validation['path']}", status="ok")
    return {"status": "success", "path": validation["path"], "previous": old_root, "validation": validation}


@app.get("/api/workspace/dirs")
def workspace_dirs_list():
    return {"status": "success", "dirs": _workspace_dirs_detail()}


@app.post("/api/workspace/dirs")
async def workspace_dirs_add(request: Request):
    """Add an additional directory with on-disk validation and access-mode selection."""
    data = await request.json()
    raw_path = str(data.get("path", "")).strip()
    access_mode = str(data.get("access_mode", "read_write")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="path is required")
    validation = _validate_workspace_path(raw_path)
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("reason", "Invalid directory"))
    target = validation["path"]
    root = _workspace_root()
    if _is_within(root, target):
        raise HTTPException(status_code=400, detail="Path is inside the workspace root and does not need to be added")
    if target == root:
        raise HTTPException(status_code=400, detail="Path is the workspace root itself")
    dirs = _RUNTIME_SETTINGS.setdefault("additional_dirs", [])
    if target in dirs:
        raise HTTPException(status_code=409, detail="Directory is already added")
    for existing in dirs:
        if _is_within(existing, target) or _is_within(target, existing):
            raise HTTPException(status_code=409, detail=f"Directory overlaps an existing additional directory: {existing}")
    if access_mode not in {"read_only", "read_write", "index_only", "disabled"}:
        access_mode = "read_write"
    dirs.append(target)
    _WORKSPACE_DIR_ACCESS[target] = access_mode
    await asyncio.to_thread(_save_runtime_preferences)
    _invalidate_workspace_summary_cache()
    apply_runtime_to_all_loops()
    _record_workspace_activity("directory_added", f"Additional directory added: {target}", status="ok")
    return {"status": "success", "path": target, "access_mode": access_mode, "additional_dirs": dirs}


@app.patch("/api/workspace/dirs")
async def workspace_dirs_update(request: Request):
    """Change the access mode of an additional directory."""
    data = await request.json()
    path = str(data.get("path", "")).strip()
    access_mode = str(data.get("access_mode", "")).strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    if access_mode not in {"read_only", "read_write", "index_only", "disabled"}:
        raise HTTPException(status_code=400, detail="Invalid access mode")
    dirs = _RUNTIME_SETTINGS.setdefault("additional_dirs", [])
    if path not in dirs:
        raise HTTPException(status_code=404, detail="Directory is not in the additional-directories list")
    _WORKSPACE_DIR_ACCESS[path] = access_mode
    _invalidate_workspace_summary_cache()
    _record_workspace_activity("directory_updated", f"Access mode for {path} set to {access_mode}", status="ok")
    return {"status": "success", "path": path, "access_mode": access_mode}


@app.delete("/api/workspace/dirs")
async def workspace_dirs_remove(request: Request):
    """Remove an additional directory from Nexus access. Does not delete files from disk."""
    path = str(request.query_params.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    dirs = _RUNTIME_SETTINGS.setdefault("additional_dirs", [])
    if path not in dirs:
        raise HTTPException(status_code=404, detail="Directory is not in the additional-directories list")
    dirs = [d for d in dirs if d != path]
    _RUNTIME_SETTINGS["additional_dirs"] = dirs
    _WORKSPACE_DIR_ACCESS.pop(path, None)
    await asyncio.to_thread(_save_runtime_preferences)
    _invalidate_workspace_summary_cache()
    apply_runtime_to_all_loops()
    _record_workspace_activity("directory_removed", f"Additional directory removed: {path}", status="ok")
    return {"status": "success", "removed": True, "note": "Files were not deleted from disk."}


@app.get("/api/files/tree")
def files_tree(path: str = ""):
    """Lazy single-level file tree for the workspace. Only the requested directory is listed."""
    root = _workspace_root()
    raw = path.strip().strip('"').strip("'")
    target = _canonical_workspace_path(raw) if raw else root
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Path does not exist")
    if not os.path.isdir(target):
        return {"status": "success", "path": os.path.relpath(target, root), "items": [{"name": os.path.basename(target), "type": "file", "path": os.path.relpath(target, root), "size": os.path.getsize(target)}]}
    if not _is_within(root, target):
        raise HTTPException(status_code=403, detail="Path is outside the workspace root")
    items = []
    try:
        entries = sorted(os.listdir(target), key=lambda e: (not os.path.isdir(os.path.join(target, e)), e.lower()))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not list directory: {exc}")
    for entry in entries:
        full = os.path.join(target, entry)
        try:
            rel = os.path.relpath(full, root).replace("\\", "/")
        except (ValueError, OSError):
            continue
        if os.path.isdir(full):
            items.append({"name": entry, "type": "directory", "path": rel})
        else:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            items.append({"name": entry, "type": "file", "path": rel, "size": size})
    return {"status": "success", "path": os.path.relpath(target, root), "items": items}


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
    command = [python, "-c", "from apps.voice.voice_chat import main; main()"]
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
        "from apps.voice.voice_chat import main; main()",
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


def _start_voice_process_sync(mode: str, session_id: str, owner_pid: int = 0) -> subprocess.Popen:
    """Prepare voice logging and launch the child process off the API loop."""
    os.makedirs(os.path.dirname(_VOICE_LOG_PATH), exist_ok=True)
    _kill_stray_voice_processes()
    try:
        with open(_VOICE_LOG_PATH, "w", encoding="utf-8") as handle:
            handle.write("")
    except Exception:
        logger.warning("server: voice log reset failed", exc_info=True)
    command = _voice_command_for_mode(mode, session_id, owner_pid=owner_pid)
    launch = _voice_launch_options(mode)
    try:
        return subprocess.Popen(
            command,
            cwd=_PROJECT_ROOT,
            stdout=launch["stdout"],
            stderr=launch["stderr"],
            stdin=launch["stdin"],
            creationflags=launch["creationflags"],
            shell=False,
        )
    except Exception:
        if launch.get("log_handle"):
            launch["log_handle"].close()
        raise


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


def get_voice_status():
    return {"status": "success", **_voice_status_payload()}


@app.post("/api/voice/start")
async def start_voice(request: Request):
    global _VOICE_PROCESS, _VOICE_MODE, _VOICE_STARTED_AT
    data = await request.json()
    requested_mode = str(data.get("mode", "auto")).strip().lower()
    mode = requested_mode if requested_mode in {"auto", "manual", "text"} else "auto"
    session_id = safe_session_id(str(data.get("session_id", "default")).strip())
    owner_pid = int(data.get("owner_pid") or 0)

    if _voice_is_running():
        return {"status": "success", **_voice_status_payload()}

    try:
        _VOICE_PROCESS = await asyncio.to_thread(
            _start_voice_process_sync, mode, session_id, owner_pid
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Voice Python runtime not found: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to start voice mode: {exc}") from exc

    await asyncio.sleep(1.0)
    if _VOICE_PROCESS.poll() is not None:
        tail = (await asyncio.to_thread(_tail_voice_log, 2000)).strip()
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


@app.get("/api/voice/statistics")
def get_voice_statistics():
    """Return comprehensive voice usage statistics."""
    try:
        from apps.voice import VoiceAssistant
        # Check if voice is properly configured
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        stats = assistant.get_voice_statistics()
        return {"status": "success", "statistics": stats}
    except Exception as e:
        logger.warning("Voice statistics failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Voice statistics", e)}


def get_voice_history(limit: int = 50):
    """Return voice transcription history."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        history = assistant.get_transcription_history(limit=limit)
        return {"status": "success", "history": history, "count": len(history)}
    except Exception as e:
        logger.warning("Voice history failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Voice history", e)}


@app.post("/api/voice/search")
async def search_voice_history(request: Request):
    """Search voice transcription history."""
    try:
        data = await request.json()
        query = data.get("query", "")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        results = assistant.search_transcriptions(query)
        
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as e:
        logger.warning("Voice search failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Voice search", e)}


@app.post("/api/voice/export")
async def export_voice_data(request: Request):
    """Export voice data in JSON or text format."""
    try:
        data = await request.json()
        format = data.get("format", "json")
        
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        exported = assistant.export_voice_data(format)
        
        return {"status": "success", "format": format, "data": exported}
    except Exception as e:
        logger.warning("Voice export failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Voice export", e)}


@app.post("/api/voice/clear-history")
def clear_voice_history():
    """Clear voice transcription history."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        assistant.clear_transcription_history()
        return {"status": "success", "message": "Voice history cleared"}
    except Exception as e:
        logger.warning("Clear voice history failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Clear voice history", e)}


@app.post("/api/voice/reset-statistics")
def reset_voice_statistics():
    """Reset voice usage statistics."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        assistant.reset_statistics()
        return {"status": "success", "message": "Voice statistics reset"}
    except Exception as e:
        logger.warning("Reset voice statistics failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Reset voice statistics", e)}


def get_available_voices():
    """Return list of available TTS voices."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        voices = assistant.get_available_voices()
        return {"status": "success", "voices": voices}
    except Exception as e:
        logger.warning("Get voices failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Get voices", e)}


def get_available_languages():
    """Return list of supported STT languages."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        languages = assistant.get_available_languages()
        return {"status": "success", "languages": languages}
    except Exception as e:
        logger.warning("Get languages failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Get languages", e)}


@app.get("/api/voice/devices")
def get_audio_devices():
    """Return available audio devices."""
    try:
        from apps.voice import VoiceAssistant
        from configure.config_loader import NexusConfigLoader
        settings = VoiceAssistant.from_config(NexusConfigLoader())
        assistant = VoiceAssistant(settings)
        devices = assistant.test_audio_devices()
        return {"status": "success", "devices": devices}
    except Exception as e:
        logger.warning("Get audio devices failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Get audio devices", e)}


async def update_voice_settings(request: Request):
    """Update voice settings."""
    try:
        data = await request.json()
        from configure.config_loader import NexusConfigLoader
        loader = NexusConfigLoader()
        
        # Get current voice config
        voice_config = loader.get("voice", {})
        if not isinstance(voice_config, dict):
            voice_config = {}
        
        # Update with provided settings
        voice_config.update(data)
        
        # Save back to config
        loader.set("voice", voice_config)
        loader.save()
        
        return {"status": "success", "message": "Voice settings updated"}
    except Exception as e:
        logger.warning("Update voice settings failed", exc_info=True)
        return {"status": "error", "message": _public_api_failure("Update voice settings", e)}


@app.post("/api/multi_agent")
async def multi_agent(request: Request):
    """Trigger a multi-agent workflow."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Multi-agent request must be an object")
    command = str(data.get("command", "") or "").strip().lower()
    prompt = str(data.get("prompt", "") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    # Simple echo for now — full implementation needs Workflow integration
    try:
        hive_engine = _get_hive_engine()
        personas = {str(name).lower(): str(name) for name in hive_engine.list_personas()}
        requested_persona = command.lstrip("/").strip().lower()
        persona = personas.get(requested_persona, personas.get("worker", "WORKER"))
        hive_id, spawned = await hive_engine.spawn_hive([(prompt, persona)])
    except Exception as exc:
        logger.warning("Multi-agent workflow launch failed", exc_info=True)
        raise HTTPException(status_code=503, detail=_public_api_failure("Multi-agent launch", exc))

    agent_summaries = [
        {"id": agent.agent_id, "task": agent.task, "persona": agent.persona, "status": agent.status}
        for agent in spawned
    ]
    with _HIVES_LOCK:
        _HIVES[hive_id] = {
            "id": hive_id,
            "status": "running",
            "agents": agent_summaries,
            "created_at": time.time(),
        }
    _persist_hive_manifest()
    return {
        "status": "started",
        "command": command,
        "hive_id": hive_id,
        "hive": {"id": hive_id, "status": "running", "agents": agent_summaries},
        "result": f"Multi-agent {command or '/run'} started. Prompt: {prompt[:100]}",
    }


@app.get("/api/engine/status")
def engine_status():
    try:
        from nexus.common.engine_manager import get_engine_status, load_or_create_config
        return {
            "status": get_engine_status(),
            "config": load_or_create_config()
        }
    except ImportError:
        return {"status": "unavailable", "config": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Engine status", e))

@app.post("/api/engine/config")
async def update_engine_config(request: Request):
    try:
        from nexus.common.engine_manager import load_or_create_config, save_config
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
        raise HTTPException(status_code=500, detail=_public_api_failure("Engine configuration", e))

@app.post("/api/engine/compile")
async def compile_engine():
    try:
        from nexus.common.engine_compiler import compile_llama_cpp
        res = compile_llama_cpp()
        return res
    except ImportError:
        raise HTTPException(status_code=501, detail="Engine compiler not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Engine compilation", e))


def _resolve_local_model_path(model_name: Any) -> Optional[str]:
    """Resolve a model name without permitting filesystem escape."""
    if model_name is None or not str(model_name).strip():
        return None
    model_root = (Path(_PROJECT_ROOT) / "models" / "local").resolve(strict=False)
    try:
        candidate = Path(str(model_name)).expanduser()
        if not candidate.is_absolute():
            candidate = model_root / candidate
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(model_root)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=403, detail="model must be inside the local model directory")
    return str(resolved)


@app.post("/api/engine/reload")
async def reload_local_engine(request: Request):
    try:
        from nexus.common.engine_manager import reload_engine
    except ImportError:
        raise HTTPException(status_code=501, detail="Engine manager not available")
    try:
        data = await request.json()
        model_name = data.get("model") if isinstance(data, dict) else None
        model_path = _resolve_local_model_path(model_name)
                
        status = reload_engine(model_path)
        return {"status": "success", "engine": status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_public_api_failure("Engine reload", e))

_active_train_process = None
_TRAIN_LOCK = threading.Lock()


def _training_status_path() -> str:
    return os.path.join(_PROJECT_ROOT, "configure", "self_improvement_status.json")


def _write_training_status(payload: Dict[str, Any]) -> None:
    """Persist a bounded training lifecycle record atomically."""
    path = _training_status_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".self_improvement_status.", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_training_status() -> Dict[str, Any]:
    try:
        with open(_training_status_path(), "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}


def _training_pid_is_alive(pid: Any) -> bool:
    try:
        numeric_pid = int(pid)
        if numeric_pid <= 0:
            return False
        os.kill(numeric_pid, 0)
        return True
    except PermissionError:
        # The process exists but belongs to another user/session.
        return True
    except (OSError, TypeError, ValueError):
        return False


def _start_training_sync(steps: int) -> Dict[str, Any]:
    """Coordinate and launch one training process outside the async loop."""
    global _active_train_process
    with _TRAIN_LOCK, _interprocess_event_lock(_training_status_path()):
        if _active_train_process and _active_train_process.poll() is None:
            return {"status": "running", "message": "Self-improvement training is already in progress."}
        persisted = _read_training_status()
        if persisted.get("status") in ("training", "running") and _training_pid_is_alive(persisted.get("pid")):
            return {
                "status": "running",
                "run_id": persisted.get("run_id", ""),
                "pid": persisted.get("pid"),
                "steps": persisted.get("steps"),
                "message": "Self-improvement training is already in progress.",
            }

        import platform
        import subprocess
        import sys

        train_script = os.path.join(_PROJECT_ROOT, "evolution", "self_improvement.py")
        run_id = uuid.uuid4().hex
        cmd = [sys.executable, train_script, str(steps)]
        creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=_PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            logger.warning("Self-improvement process launch failed", exc_info=True)
            raise HTTPException(status_code=503, detail=_public_api_failure("Training launch", exc))
        _active_train_process = proc
        try:
            _write_training_status({
                "status": "training",
                "run_id": run_id,
                "pid": proc.pid,
                "steps": steps,
                "started_at": time.time(),
            })
        except Exception:
            logger.warning("Could not persist training start status", exc_info=True)
    return {"status": "started", "run_id": run_id, "pid": proc.pid, "steps": steps,
            "message": f"Self-improvement training session started with {steps} steps."}

@app.post("/api/engine/train")
async def train_local_engine(request: Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Training request must be an object")
    raw_steps = data.get("steps", 50)
    if isinstance(raw_steps, bool):
        raise HTTPException(status_code=400, detail="steps must be an integer between 1 and 10000")
    try:
        steps = int(raw_steps)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="steps must be an integer between 1 and 10000")
    if not 1 <= steps <= 10000:
        raise HTTPException(status_code=400, detail="steps must be an integer between 1 and 10000")
    return await asyncio.to_thread(_start_training_sync, steps)

@app.get("/api/engine/train/status")
def train_status():
    global _active_train_process

    status_file = _training_status_path()
    status = {"status": "idle", "message": "No training has been run yet."}

    if os.path.exists(status_file):
        status = _read_training_status()
        if not status:
            logger.warning("Training status file was invalid or unreadable")

    is_running = _active_train_process and _active_train_process.poll() is None
    if is_running:
        status["is_running"] = True
        if status.get("status") in ("completed", "failed"):
            status["status"] = "training"
    else:
        status["is_running"] = False
        if _active_train_process:
            exit_code = _active_train_process.poll()
            if exit_code != 0 and status.get("status") not in ("completed", "failed"):
                status["status"] = "failed"
                status["error"] = f"Training process terminated unexpectedly with code {exit_code}."
                status["message"] = f"Failed: Process exited with code {exit_code}."
            elif exit_code == 0 and status.get("status") == "training":
                status["status"] = "completed"
                status["message"] = "Training process completed."
        elif status.get("status") in ("training", "running"):
            status["status"] = "orphaned"
            status["message"] = "Training state was found without a live process after server recovery."

    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
