"""Authoritative base registry.

Every component category (tools, skills, plugins, MCP, gateways, models,
providers, agents, agent teams, workflows, memory, queues, sandboxes,
integrations) gets exactly one registry. This base provides the common
contract: register, unregister, get, list, enable/disable, and persistence of
the enable/disable state. Subclasses add category-specific load/validate.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class RegistryState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"
    FAILED = "failed"


@dataclass
class RegistryEntry(Generic[T]):
    id: str
    component: T
    state: RegistryState = RegistryState.ENABLED
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class BaseRegistry(ABC, Generic[T]):
    category: str = "base"

    def __init__(self, state_path: Optional[str] = None) -> None:
        self._entries: Dict[str, RegistryEntry[T]] = {}
        self._state_path = state_path

    # -- registration -----------------------------------------------------
    def register(self, id: str, component: T, metadata: Optional[Dict[str, Any]] = None,
                 enabled: bool = True) -> RegistryEntry[T]:
        if not id:
            raise ValueError("registry id must be non-empty")
        entry = RegistryEntry(
            id=id,
            component=component,
            state=RegistryState.ENABLED if enabled else RegistryState.DISABLED,
            metadata=metadata or {},
        )
        self._entries[id] = entry
        return entry

    def unregister(self, id: str) -> None:
        self._entries.pop(id, None)

    def get(self, id: str) -> Optional[T]:
        entry = self._entries.get(id)
        return entry.component if entry else None

    def entry(self, id: str) -> Optional[RegistryEntry[T]]:
        return self._entries.get(id)

    def has(self, id: str) -> bool:
        return id in self._entries

    # -- lifecycle state --------------------------------------------------
    def set_state(self, id: str, state: RegistryState) -> None:
        entry = self._entries.get(id)
        if entry is None:
            raise KeyError(f"Unknown registry entry {id!r}")
        entry.state = state
        self._persist_state()

    def enable(self, id: str) -> None:
        self.set_state(id, RegistryState.ENABLED)

    def disable(self, id: str) -> None:
        self.set_state(id, RegistryState.DISABLED)

    def quarantine(self, id: str, error: Optional[str] = None) -> None:
        entry = self._entries.get(id)
        if entry is None:
            raise KeyError(f"Unknown registry entry {id!r}")
        entry.state = RegistryState.QUARANTINED
        entry.error = error
        self._persist_state()

    @property
    def enabled_ids(self) -> List[str]:
        return [i for i, e in self._entries.items() if e.state == RegistryState.ENABLED]

    @property
    def ids(self) -> List[str]:
        return list(self._entries)

    @abstractmethod
    def validate(self, component: T) -> None:
        """Raise on an invalid component; subclasses implement category checks."""
        raise NotImplementedError

    # -- persistence (enable/disable state only; not the components) -------
    def _persist_state(self) -> None:
        if not self._state_path:
            return
        try:
            data = {i: e.state.value for i, e in self._entries.items()}
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass  # best-effort; runtime state must not crash on write failure

    def _load_state(self) -> None:
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for i, st in data.items():
                if i in self._entries:
                    self._entries[i].state = RegistryState(st)
        except (OSError, json.JSONDecodeError):
            pass
