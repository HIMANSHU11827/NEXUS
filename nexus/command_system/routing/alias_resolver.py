"""Alias resolver: maps alternative command spellings to canonical names.

Aliases let surfaces and humans use short or natural forms (``task ls``,
``tasks``, ``t.list``) without re-implementing logic. The bus resolves before
dispatch, so only canonical names ever reach a handler.
"""

from __future__ import annotations

from typing import Dict


class AliasResolver:
    def __init__(self) -> None:
        self._aliases: Dict[str, str] = {}

    def add(self, alias: str, canonical: str) -> None:
        self._aliases[alias.strip().lower()] = canonical

    def remove(self, alias: str) -> None:
        self._aliases.pop(alias.strip().lower(), None)

    def resolve(self, command: str) -> str:
        return self._aliases.get(command.strip().lower(), command)
