"""A small, reusable finite state machine used for lifecycle coordination."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional, Set

from nexus.core.errors import LifecycleError


class StateMachine:
    """Directed transition machine with optional guards and exit/entry hooks.

    Transitions are declared as ``(source, target)`` edges. Wildcards are
    supported: ``"*"`` as a source matches any state; a ``guard`` callable may
    veto a transition; ``on_enter`` / ``on_exit`` hooks run around the change.
    """

    def __init__(self, initial: str) -> None:
        self._state = initial
        self._edges: Set[tuple[str, str]] = set()
        self._guards: Dict[tuple[str, str], Callable[[], bool]] = {}
        self._on_enter: Dict[str, Callable[[str], None]] = {}
        self._on_exit: Dict[str, Callable[[str], None]] = {}

    @property
    def state(self) -> str:
        return self._state

    def add_transition(self, source: str, target: str) -> "StateMachine":
        self._edges.add((source, target))
        return self

    def add_transitions(self, edges: Iterable[tuple[str, str]]) -> "StateMachine":
        for s, t in edges:
            self.add_transition(s, t)
        return self

    def set_guard(self, source: str, target: str, guard: Callable[[], bool]) -> None:
        self._guards[(source, target)] = guard

    def on_enter(self, state: str, hook: Callable[[str], None]) -> None:
        self._on_enter[state] = hook

    def on_exit(self, state: str, hook: Callable[[str], None]) -> None:
        self._on_exit[state] = hook

    def can_transition(self, target: str) -> bool:
        if target == self._state:
            return True
        if (self._state, target) in self._edges or ("*", target) in self._edges:
            guard = self._guards.get((self._state, target)) or self._guards.get(("*", target))
            if guard is not None:
                return guard()
            return True
        return False

    def transition(self, target: str) -> str:
        if not self.can_transition(target):
            raise LifecycleError(
                f"Illegal transition {self._state!r} -> {target!r}"
            )
        if target == self._state:
            return self._state
        exit_hook = self._on_exit.get(self._state)
        if exit_hook is not None:
            exit_hook(self._state)
        previous = self._state
        self._state = target
        enter_hook = self._on_enter.get(target)
        if enter_hook is not None:
            enter_hook(previous)
        return previous
