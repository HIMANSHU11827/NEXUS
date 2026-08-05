"""HyperKernel — minimal, honest per-module health-snapshot registry.

This is deliberately small. It is NOT a full meta-reasoning kernel: it stores a
health snapshot (module, status, ok, error, last_check) per registered check so
callers can truthfully answer "is module X healthy right now?" without
pretending to be a real hypervisor.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

IS_STUB = False


class HyperKernel:
    """Registry that runs registered health checks and snapshots their status."""

    is_stub = False

    def __init__(self, root: str) -> None:
        self.root = root
        self._checks: Dict[str, Dict[str, Any]] = {}
        self._snapshots: Dict[str, Dict[str, Any]] = {}

    # ── Registration ───────────────────────────────────────────────────

    def register_check(self, name: str, check: Callable[[], Any], module: Optional[str] = None) -> None:
        """Register ``check()`` (returns bool or dict with ok/status/error)."""
        if not callable(check):
            raise TypeError(f"HyperKernel.register_check: check for {name!r} must be callable")
        self._checks[name] = {"fn": check, "module": module or str(name), "registered_at": time.time()}

    # ── Check running ──────────────────────────────────────────────────

    def check_all(self, names: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Run registered checks (or the select ``names``) and snapshot results.

        A raising check is snapshotted as status="error" and never propagates.
        """
        targets = names if names is not None else list(self._checks)
        results: Dict[str, Dict[str, Any]] = {}
        for name in targets:
            cfg = self._checks.get(name)
            if cfg is None:
                snapshot = _snapshot(name, False, "no check registered under this name")
            else:
                snapshot = self._run_check(name, cfg)
            self._snapshots[name] = snapshot
            results[name] = snapshot
        return results

    def _run_check(self, name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        try:
            output = cfg["fn"]()
        except Exception as exc:  # a failing check never takes down check_all
            return _snapshot(cfg["module"], False, f"{type(exc).__name__}: {exc}")
        if isinstance(output, dict):
            ok = bool(output.get("ok", _default_ok(output.get("status"))))
            status = str(output.get("status") or ("ok" if ok else "error"))
            error = str(output.get("error") or "")
            return {
                "module": cfg["module"],
                "status": status,
                "ok": ok,
                "error": error,
                "details": output,
                "last_check": time.time(),
            }
        ok = bool(output)
        return _snapshot(cfg["module"], ok, "" if ok else "check returned falsy")

    def snapshot(self, name: str) -> Optional[Dict[str, Any]]:
        """Last snapshot for a module, or None if it has never been checked."""
        return self._snapshots.get(name)

    # ── Summary ────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        total = len(self._snapshots)
        ok_count = sum(1 for snap in self._snapshots.values() if snap.get("ok"))
        error_count = sum(1 for snap in self._snapshots.values() if snap.get("status") == "error")
        return {
            "status": "ok",
            "is_stub": False,
            "module": "HyperKernel",
            "registered_checks": len(self._checks),
            "snapshot_count": total,
            "ok": ok_count,
            "error": error_count,
            "unchecked": max(0, len(self._checks) - total),
            "modules": [
                {
                    "name": name,
                    "module": snap.get("module"),
                    "status": snap.get("status"),
                    "ok": snap.get("ok"),
                    "last_check": snap.get("last_check"),
                }
                for name, snap in self._snapshots.items()
            ],
        }


def _snapshot(module: str, ok: bool, error: str) -> Dict[str, Any]:
    return {
        "module": module,
        "status": "ok" if ok else "error",
        "ok": bool(ok),
        "error": error or "",
        "last_check": time.time(),
    }


def _default_ok(status: Any) -> bool:
    if status is None:
        return True
    return str(status).lower() in ("ok", "true", "pass", "healthy")
