"""
NEXUS Profile Schema — Pydantic models for profile metadata.

Each profile has a profile.yaml that defines:
  - name:          Unique profile name
  - inherits:      Parent profile (empty string for base)
  - description:   Human-readable description
  - tags:          Categorization tags
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProfileMeta:
    """Metadata for a NEXUS profile."""

    name: str
    inherits: str = "base"
    description: str = ""
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileMeta":
        return cls(
            name=data.get("name", "unknown"),
            inherits=data.get("inherits", "base"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
        )


@dataclass
class ProfileRegistry:
    """Registry of known profiles — read from configs/profiles.yaml."""

    active: str = "default"
    profiles: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileRegistry":
        return cls(
            active=data.get("active", "default"),
            profiles=data.get("profiles", {}),
        )
