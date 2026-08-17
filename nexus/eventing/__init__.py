"""Canonical event system.

Thin, dependency-light event bus + store + dispatcher used by every subsystem to
publish and subscribe to system events. The legacy ``nexus.events`` module
(``CanonicalEvent``) remains the historical canonical event source; this package
lives at ``nexus.eventing`` specifically so it does NOT shadow that module. New
subsystems should adopt this typed infrastructure going forward.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

Subscriber = Callable[["Event"], None]


class EventType(str, Enum):
    SYSTEM = "system"
    LIFECYCLE = "lifecycle"
    COMMAND = "command"
    TASK = "task"
    GOAL = "goal"
    COMPONENT = "component"
    LEARNING = "learning"
    EVOLUTION = "evolution"
    CUSTOM = "custom"


@dataclass
class Event:
    type: str
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(
            type=data.get("type", "custom"),
            name=data["name"],
            payload=data.get("payload", {}),
            id=data.get("id", uuid.uuid4().hex),
            timestamp=data.get("timestamp", time.time()),
            source=data.get("source"),
        )


class EventBus:
    """Async pub/sub bus with topic filtering and in-memory store."""

    def __init__(self, store: Optional["EventStore"] = None) -> None:
        self._subscribers: Dict[str, List[Subscriber]] = {}
        self._global: List[Subscriber] = []
        self._store = store or EventStore()

    def subscribe(self, topic: str, fn: Subscriber) -> None:
        self._subscribers.setdefault(topic, []).append(fn)

    def subscribe_all(self, fn: Subscriber) -> None:
        self._global.append(fn)

    def publish(self, event: Event) -> None:
        self._store.append(event)
        for fn in self._global:
            self._safe(fn, event)
        for fn in self._subscribers.get(event.name, []):
            self._safe(fn, event)
        for fn in self._subscribers.get(event.type, []):
            self._safe(fn, event)

    async def publish_async(self, event: Event) -> None:
        self.publish(event)

    def _safe(self, fn: Subscriber, event: Event) -> None:
        try:
            fn(event)
        except Exception:  # noqa: BLE001 - subscriber must not break the bus
            pass

    def history(self, limit: Optional[int] = None) -> List[Event]:
        return self._store.history(limit)


class EventStore:
    """Append-only in-memory event log (bounded)."""

    def __init__(self, maxlen: int = 10_000) -> None:
        self._events: List[Event] = []
        self._maxlen = maxlen

    def append(self, event: Event) -> None:
        self._events.append(event)
        if len(self._events) > self._maxlen:
            self._events = self._events[-self._maxlen:]

    def history(self, limit: Optional[int] = None) -> List[Event]:
        if limit is None:
            return list(self._events)
        return self._events[-limit:]

    def to_json(self, limit: Optional[int] = None) -> str:
        return json.dumps([e.to_dict() for e in self.history(limit)], indent=2)


class EventDispatcher:
    """Routes events to registered handlers by name/type."""

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        self.bus = bus or EventBus()
        self._handlers: Dict[str, Callable[[Event], None]] = {}

    def register_handler(self, name: str, fn: Callable[[Event], None]) -> None:
        self._handlers[name] = fn
        self.bus.subscribe(name, fn)

    def dispatch(self, event: Event) -> None:
        self.bus.publish(event)
