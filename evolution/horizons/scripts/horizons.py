"""StrategicHorizons — long-term roadmap and strategic planning.

Provides a default set of strategic horizons that the prompt engine and
runtime queries use to ground the model in NEXUS's near/mid/far-term
concerns. Persisted planning is a future upgrade; for now this returns a
stable, sensible default set so callers (e.g. ``prompts/__init__.py``'s
``kernel.horizons.get_active_horizons()``) get real data instead of an
AttributeError.
"""

from __future__ import annotations

from typing import Any, Dict, List


class StrategicHorizons:
    """Long-term roadmap / strategic planning subsystem.

    Constructor-only before this fix: every caller of ``get_active_horizons``
    crashed. It now exposes a small, fixed set of horizons across three
    planning scales.
    """

    DEFAULT_HORIZONS: List[Dict[str, Any]] = [
        {
            "name": "immediate",
            "scale": "days",
            "timespan": "1-3 days",
            "focus": "Ship current tasks, fix bugs, keep the feedback loop closed.",
            "status": "active",
        },
        {
            "name": "near_term",
            "scale": "weeks",
            "timespan": "1-4 weeks",
            "focus": "Stabilize subsystems, strengthen verification, expand test coverage.",
            "status": "active",
        },
        {
            "name": "mid_term",
            "scale": "quarters",
            "timespan": "1-3 months",
            "focus": "Deepen self-evolution, memory consolidation, and multi-agent coordination.",
            "status": "planned",
        },
        {
            "name": "long_term",
            "scale": "years",
            "timespan": "6+ months",
            "focus": "Autonomous engineering mastery and reliable long-horizon autonomy.",
            "status": "vision",
        },
    ]

    def __init__(self, root: str):
        self.root = root

    def get_active_horizons(self) -> List[Dict[str, Any]]:
        """Return the currently active strategic horizons."""
        return [h for h in self.DEFAULT_HORIZONS if h.get("status") == "active"]

    def get_horizons(self) -> List[Dict[str, Any]]:
        """Return all known strategic horizons."""
        return list(self.DEFAULT_HORIZONS)

    def list_horizons(self) -> List[Dict[str, Any]]:
        """Alias for :meth:`get_horizons`."""
        return self.get_horizons()
