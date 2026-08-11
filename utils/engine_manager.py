"""Durable lifecycle state for the optional local llama.cpp engine.

This module does not build or load a native engine itself.  It owns the
configuration/status contract used by the API and reports readiness only when
an actual model artifact is present, avoiding the previous fake-success paths.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from copy import deepcopy
from typing import Any, Dict, Optional

logger = logging.getLogger("nexus.engine_manager")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_PATH = os.environ.get("NEXUS_ENGINE_CONFIG", os.path.join(_ROOT, "config", "engine.json"))
STATUS_PATH = os.environ.get("NEXUS_ENGINE_STATUS", os.path.join(_ROOT, ".nexus", "llama_cpp_status.json"))
_LOCK = threading.RLock()

_DEFAULT_CONFIG: Dict[str, Any] = {
    "llama_cpp_params": {},
    "system": {},
    "default_model": "",
}


def _atomic_json_write(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp",
        dir=os.path.dirname(os.path.abspath(path)),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
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
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read engine state file", exc_info=True)
        return {}


def load_or_create_config() -> Dict[str, Any]:
    """Load engine settings while preserving the stable public shape."""
    with _LOCK:
        loaded = _read_json(_CONFIG_PATH)
        config = deepcopy(_DEFAULT_CONFIG)
        for key in config:
            if key in loaded and isinstance(loaded[key], type(config[key])):
                config[key] = loaded[key]
        if not os.path.exists(_CONFIG_PATH):
            _atomic_json_write(_CONFIG_PATH, config)
        return config


def save_config(config: Dict[str, Any]) -> None:
    """Persist validated engine settings atomically."""
    if not isinstance(config, dict):
        raise TypeError("engine config must be a mapping")
    normalized = deepcopy(_DEFAULT_CONFIG)
    for key in normalized:
        value = config.get(key, normalized[key])
        if not isinstance(value, type(normalized[key])):
            raise TypeError(f"engine config field {key!r} has an invalid type")
        normalized[key] = value
    with _LOCK:
        _atomic_json_write(_CONFIG_PATH, normalized)


def _status_payload(*, model_path: str = "", status: str = "not_ready", reason: str = "") -> Dict[str, Any]:
    return {
        "compiled": status == "ready",
        "engine": "llama.cpp",
        "status": status,
        "model_path": model_path,
        **({"reason": reason} if reason else {}),
    }


def get_engine_status() -> Dict[str, Any]:
    """Return honest persisted status, downgrading stale ready state."""
    with _LOCK:
        status = _read_json(STATUS_PATH)
        model_path = str(status.get("model_path", "") or "")
        if status.get("status") == "ready" and model_path and os.path.isfile(model_path):
            return _status_payload(model_path=model_path, status="ready")
        if model_path and not os.path.isfile(model_path):
            return _status_payload(model_path=model_path, reason="model_artifact_missing")
        return _status_payload(reason=str(status.get("reason", "not_configured")))


def reload_engine(model_path: Optional[str] = None) -> Dict[str, Any]:
    """Validate and record a local model for use by the optional engine.

    Native model loading remains provider-specific; this function deliberately
    returns ``not_ready`` instead of claiming success when no artifact exists.
    """
    with _LOCK:
        config = load_or_create_config()
        selected = str(model_path or config.get("default_model", "") or "").strip()
        if not selected:
            result = _status_payload(reason="model_not_configured")
        else:
            selected = os.path.abspath(selected)
            if not os.path.isfile(selected):
                result = _status_payload(model_path=selected, reason="model_artifact_missing")
            else:
                config["default_model"] = selected
                save_config(config)
                result = _status_payload(model_path=selected, status="ready")
        _atomic_json_write(STATUS_PATH, result)
        return result
