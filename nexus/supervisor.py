"""Cross-platform durable supervisor for the Nexus API process.

The FastAPI process supervises workers it owns, but cannot restart itself.
This small parent process is the deployment-safe outer loop for unattended
operation: it probes readiness, restarts bounded failures, and quarantines a
crash loop in a durable incident file instead of spinning forever.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Iterable, List, Optional

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    # os.kill(pid, 0) is not a usable existence probe on Windows: signal 0 maps
    # to CTRL_C_EVENT and is delivered to the console group, which can inject a
    # real KeyboardInterrupt into an unrelated process. Probe via the process
    # handle instead. The explicit signatures keep 64-bit HANDLEs intact.
    _KERNEL32 = ctypes.windll.kernel32
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _ERROR_ACCESS_DENIED = 5


def _atomic_json(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


class NexusSupervisor:
    """Parent-process supervisor with durable crash-loop quarantine."""

    def __init__(
        self,
        root: str,
        command: Optional[Iterable[str]] = None,
        *,
        health_url: str = "http://127.0.0.1:8000/api/health",
        interval: float = 2.0,
        startup_timeout: float = 30.0,
        max_restarts: int = 5,
        crash_window: float = 300.0,
        incident_path: Optional[str] = None,
        lock_path: Optional[str] = None,
    ) -> None:
        self.root = os.path.abspath(root or os.getcwd())
        self.command = list(command or (sys.executable, "-m", "server"))
        self.health_url = str(health_url)
        self.interval = max(0.1, float(interval))
        self.startup_timeout = max(self.interval, float(startup_timeout))
        self.max_restarts = max(1, int(max_restarts))
        self.crash_window = max(1.0, float(crash_window))
        self.incident_path = os.path.abspath(
            incident_path or os.path.join(self.root, ".nexus", "supervisor_incident.json")
        )
        self.lock_path = os.path.abspath(
            lock_path or os.path.join(self.root, ".nexus", "supervisor.lock")
        )
        self._lock_owned = False
        self._stopping = False

    def stop(self, *_args: Any) -> None:
        self._stopping = True

    def probe(self) -> bool:
        """Return true only for a successful, JSON-readable readiness response."""
        try:
            with urllib.request.urlopen(self.health_url, timeout=min(5.0, self.interval * 2)) as response:
                if int(getattr(response, "status", 200)) >= 500:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                return isinstance(payload, dict) and str(payload.get("status") or "").lower() in {"ok", "healthy"}
        except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
            return False

    def _incident(self) -> Dict[str, Any]:
        payload = _read_json(self.incident_path)
        now = time.time()
        failures = [
            float(item) for item in payload.get("failures", [])
            if isinstance(item, (int, float)) and now - float(item) <= self.crash_window
        ]
        return {**payload, "failures": failures}

    def record_failure(self, error: str) -> Dict[str, Any]:
        prior = self._incident()
        now = time.time()
        failures = list(prior.get("failures", [])) + [now]
        failures = failures[-self.max_restarts:]
        quarantined = len(failures) >= self.max_restarts
        payload = {
            "version": 1,
            "state": "quarantined" if quarantined else "recovering",
            "failures": failures,
            "failure_count": len(failures),
            "max_restarts": self.max_restarts,
            "crash_window": self.crash_window,
            "last_error": str(error or "")[:1000],
            "updated_at": now,
        }
        _atomic_json(self.incident_path, payload)
        return payload

    def clear_quarantine(self) -> None:
        _atomic_json(self.incident_path, {
            "version": 1, "state": "clear", "failures": [],
            "failure_count": 0, "cleared_at": time.time(),
        })

    def is_quarantined(self) -> bool:
        incident = self._incident()
        return str(incident.get("state") or "") == "quarantined" and bool(incident.get("failures"))

    @staticmethod
    def _pid_alive(pid: Any) -> bool:
        try:
            value = int(pid)
            if value <= 0:
                return False
            if os.name == "nt":
                return NexusSupervisor._pid_alive_windows(value)
            os.kill(value, 0)
            return True
        except PermissionError:
            return True
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _pid_alive_windows(pid: int) -> bool:
        """Existence probe via OpenProcess — never sends signals.

        A handle means the process exists (or we could not open it because it
        is protected: ERROR_ACCESS_DENIED -> treat as alive). With a handle,
        STILL_ACTIVE (259) exit code means the process is running.
        """
        handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return _KERNEL32.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            exit_code = wintypes.DWORD()
            if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == _STILL_ACTIVE
        finally:
            _KERNEL32.CloseHandle(handle)

    def _acquire_lock(self) -> bool:
        """Acquire the durable singleton supervisor lock.

        The lock is intentionally a small PID record rather than an in-memory
        flag: a second supervisor must fail closed, while a lock left by a
        crashed parent can be reclaimed after its PID is demonstrably dead.
        """
        directory = os.path.dirname(self.lock_path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {"pid": os.getpid(), "started_at": time.time()}
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                try:
                    os.write(descriptor, json.dumps(payload, separators=(",", ":")).encode("utf-8"))
                finally:
                    os.close(descriptor)
                self._lock_owned = True
                return True
            except FileExistsError:
                existing = _read_json(self.lock_path)
                if self._pid_alive(existing.get("pid")):
                    return False
                try:
                    os.unlink(self.lock_path)
                except FileNotFoundError:
                    continue
                except OSError:
                    return False
        return False

    def _release_lock(self) -> None:
        if not self._lock_owned:
            return
        self._lock_owned = False
        try:
            existing = _read_json(self.lock_path)
            if int(existing.get("pid", -1)) == os.getpid():
                os.unlink(self.lock_path)
        except (OSError, TypeError, ValueError):
            pass

    def _dispatch_quarantine_alert(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort durable alert; a broken notifier never changes quarantine."""
        try:
            from queues.alerts import dispatch_incident
            return dispatch_incident(
                self.root,
                {**incident, "source": "supervisor"},
                event="nexus.supervisor.quarantined",
                source="supervisor",
            )
        except Exception as exc:
            return {"status": "failed", "error": str(exc)[:1000]}

    @staticmethod
    def _terminate(process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def run(self, *, clear_quarantine: bool = False) -> int:
        """Run until operator stop or durable crash-loop quarantine."""
        if not self._acquire_lock():
            return 3
        process: Optional[subprocess.Popen[Any]] = None
        backoff = self.interval
        try:
            if clear_quarantine:
                self.clear_quarantine()
            if self.is_quarantined():
                self._dispatch_quarantine_alert(self._incident())
                return 2
            while not self._stopping:
                process = subprocess.Popen(self.command, cwd=self.root, env=os.environ.copy())
                started = time.monotonic()
                healthy = False
                while not self._stopping and process.poll() is None:
                    if self.probe():
                        healthy = True
                        break
                    if time.monotonic() - started >= self.startup_timeout:
                        break
                    time.sleep(self.interval)
                if not healthy:
                    self._terminate(process)
                    incident = self.record_failure("supervised process failed readiness")
                else:
                    backoff = self.interval
                    while not self._stopping and process.poll() is None:
                        if not self.probe():
                            time.sleep(self.interval)
                            if not self.probe():
                                self._terminate(process)
                                break
                        else:
                            time.sleep(self.interval)
                    # Only an operator-requested stop is expected. A child
                    # which becomes healthy and then exits unexpectedly must
                    # count toward the crash budget even when its exit code is
                    # zero, otherwise a clean-exit loop restarts forever.
                    if self._stopping:
                        incident = {}
                    else:
                        incident = self.record_failure(
                            "supervised process exited unexpectedly or became unhealthy"
                        )
                if self._stopping:
                    break
                if incident.get("state") == "quarantined":
                    self._dispatch_quarantine_alert(incident)
                    return 2
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
        except KeyboardInterrupt:
            self._stopping = True
        finally:
            if process is not None:
                self._terminate(process)
            self._release_lock()
        return 0


def run_supervisor(root: str, *, clear_quarantine: bool = False) -> int:
    supervisor = NexusSupervisor(
        root,
        interval=float(os.environ.get("NEXUS_SUPERVISOR_INTERVAL", "2")),
        startup_timeout=float(os.environ.get("NEXUS_SUPERVISOR_STARTUP_TIMEOUT", "30")),
        max_restarts=int(os.environ.get("NEXUS_SUPERVISOR_MAX_RESTARTS", "5")),
        crash_window=float(os.environ.get("NEXUS_SUPERVISOR_CRASH_WINDOW", "300")),
    )
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, supervisor.stop)
        except (OSError, ValueError):
            pass
    return supervisor.run(clear_quarantine=clear_quarantine)


__all__ = ["NexusSupervisor", "run_supervisor"]
