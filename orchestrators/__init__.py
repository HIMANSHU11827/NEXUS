"""Orchestrators for agent loop execution: main loop and sub-agent coordination.

The canonical loop is ``NexusLoopV5`` from ``orchestrators.v5``.
For backward compatibility, ``NexusLoop`` is re-exported from V5.
"""

from orchestrators.v5.core import NexusLoopV5

# Backward-compatible alias
NexusLoop = NexusLoopV5

__all__ = ["NexusLoopV5", "NexusLoop"]
