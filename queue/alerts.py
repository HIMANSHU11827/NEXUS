"""Durable, opt-in incident alert delivery.

Alerts are deliberately separate from worker execution.  If no webhook is
configured, incidents remain visible through the local metrics API and no
network request is made.  Configured deliveries are deduplicated and their
outcome is persisted so a restart can retry a failed notification.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


def _ledger_path(root: str, fingerprint: str) -> str:
    return os.path.join(os.path.abspath(root), ".nexus", "alerts", f"{fingerprint}.json")


def _write(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".alert-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def dispatch_incident(root: str, incident: Dict[str, Any], *, url: Optional[str] = None,
                      timeout: float = 5.0, event: str = "nexus.queue.quarantined",
                      source: str = "queue") -> Dict[str, Any]:
    """Deliver one quarantine incident at most once per fingerprint."""
    first = (incident.get("failures") or [incident.get("updated_at", 0)])[0]
    fingerprint = hashlib.sha256(
        f"{source}|{event}|{incident.get('state')}|{incident.get('failure_count')}|{first}|{incident.get('last_error', '')}".encode()
    ).hexdigest()[:32]
    path = _ledger_path(root, fingerprint)
    prior: Dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
            if isinstance(value, dict):
                prior = value
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if prior.get("status") == "sent":
        return {**prior, "fingerprint": fingerprint, "deduplicated": True}

    target = str(url or os.environ.get("NEXUS_ALERT_WEBHOOK_URL", "")).strip()
    if not target:
        result = {"status": "disabled", "fingerprint": fingerprint, "updated_at": time.time()}
        _write(path, result)
        return result
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        result = {"status": "failed", "error": "alert webhook must be an HTTP(S) URL",
                  "fingerprint": fingerprint, "updated_at": time.time()}
        _write(path, result)
        return result

    body = json.dumps({
        "event": str(event or "nexus.queue.quarantined"),
        "source": str(source or "queue"),
        "fingerprint": fingerprint,
        "incident": {key: incident.get(key) for key in (
            "state", "failure_count", "max_restarts", "window_seconds", "last_error", "updated_at"
        )},
    }).encode("utf-8")
    request = urllib.request.Request(target, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "Nexus-Runtime-Alert/1",
    })
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            code_value = getattr(response, "status", None)
            code = int(code_value if code_value is not None else response.getcode())
        if code < 200 or code >= 300:
            raise RuntimeError(f"webhook returned HTTP {code}")
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)[:1000],
                  "fingerprint": fingerprint, "updated_at": time.time()}
        _write(path, result)
        return result
    result = {"status": "sent", "fingerprint": fingerprint, "updated_at": time.time()}
    _write(path, result)
    return result


__all__ = ["dispatch_incident"]
