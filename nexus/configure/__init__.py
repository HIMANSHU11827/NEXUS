"""Authoritative configuration loader with documented precedence.

Precedence (lowest to highest):
    built-in defaults
    -> environment configuration
    -> project configuration
    -> user configuration
    -> profile configuration
    -> explicit overrides
    -> environment variables
    -> runtime overrides

The loader resolves a layered configuration from (in order): built-in defaults,
an optional YAML/JSON config file, a profile file, explicit overrides, and
runtime overrides. Environment variables can override any key using the prefix
``NEXUS_`` (e.g. ``NEXUS_LOG_LEVEL=debug`` -> ``log.level``).

This replaces the ad-hoc ``config/config_loader.py`` precedence for new code;
the legacy loader remains for backward compatibility during migration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_to_nested(env: Dict[str, str], prefix: str = "NEXUS_") -> Dict[str, Any]:
    """Convert NEXUS_A_B=c into {a: {b: c}}."""
    out: Dict[str, Any] = {}
    for key, val in env.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_")
        node = out
        for p in parts[:-1]:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                break
        else:
            node[parts[-1]] = _coerce(val)
    return out


def _coerce(val: str) -> Any:
    low = val.strip().lower()
    if low in ("true", "yes", "1"):
        return True
    if low in ("false", "no", "0"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


@dataclass
class ConfigureManager:
    defaults: Dict[str, Any] = field(default_factory=dict)
    env_config: Dict[str, Any] = field(default_factory=dict)
    project_config: Dict[str, Any] = field(default_factory=dict)
    user_config: Dict[str, Any] = field(default_factory=dict)
    profile_config: Dict[str, Any] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)
    runtime_overrides: Dict[str, Any] = field(default_factory=dict)
    env_var_prefix: str = "NEXUS_"

    def resolve(self) -> Dict[str, Any]:
        layers: List[Dict[str, Any]] = [
            self.defaults,
            self.env_config,
            self.project_config,
            self.user_config,
            self.profile_config,
            self.overrides,
            _env_to_nested(dict(os.environ), self.env_var_prefix),
            self.runtime_overrides,
        ]
        merged: Dict[str, Any] = {}
        for layer in layers:
            if layer:
                merged = _deep_merge(merged, layer)
        return merged

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.resolve()
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set_runtime(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        node = self.runtime_overrides
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
