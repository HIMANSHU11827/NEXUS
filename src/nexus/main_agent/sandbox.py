"""V5Sandbox - sandbox tiers and risk scoring for the V5 loop.

Tiers: NO_SANDBOX (direct), NORMAL (workspace-only), DOCKER (container).
Wraps sandbox.SovereignSandbox + CommandRiskScorer.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, Optional


logger = logging.getLogger(__name__)


class V5Sandbox:
    """Mixin giving the V5 loop sandbox tiers and risk scoring.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.runtime`` - dataclass carrying ``sandbox`` (``SovereignSandbox``,
      init None) and ``risk_scorer`` (``CommandRiskScorer``, init None); may
      be None in exotic cases, everything is guarded.
    - ``self.root_dir`` - project root passed to ``SovereignSandbox``.
    - ``self.logger`` - logger exposing ``.info``/``.warning``/``.debug``.
    """

    def _init_security(self):
        """Initialize security components from V1."""
        try:
            from sandbox.risk import CommandRiskScorer
            from sandbox.sandbox_manager import SovereignSandbox
            self.runtime.risk_scorer = CommandRiskScorer()
            self.runtime.sandbox = SovereignSandbox(self.root_dir)
            self.logger.info("V5 loop security initialized")
        except Exception as e:
            self.logger.warning(f"Could not initialize security: {e}")

    def _sandbox(self):
        """Return the active sandbox, re-initializing it if missing. Never raises."""
        sandbox = getattr(self.runtime, "sandbox", None)
        if sandbox is not None:
            return sandbox
        try:
            self._init_security()
        except Exception as e:
            self.logger.warning(f"[SANDBOX] re-init failed: {e}")
        return getattr(self.runtime, "sandbox", None)

    def _risk_scorer(self):
        """Return the active risk scorer, re-initializing it if missing. Never raises."""
        scorer = getattr(self.runtime, "risk_scorer", None)
        if scorer is not None:
            return scorer
        try:
            self._init_security()
        except Exception as e:
            self.logger.warning(f"[SANDBOX] risk scorer re-init failed: {e}")
        return getattr(self.runtime, "risk_scorer", None)

    def _sandbox_tier(self) -> str:
        """Return the sandbox tier as a string, or "" when unavailable."""
        sandbox = self._sandbox()
        if sandbox is None:
            return ""
        tier = getattr(sandbox, "tier", None)
        if tier is None:
            return ""
        value = getattr(tier, "value", None)
        if isinstance(value, str):
            return value
        if isinstance(tier, str):
            return tier
        return ""

    def _set_sandbox_tier(self, tier: Any) -> bool:
        """Set the sandbox tier from a string or SandboxTier member. Never raises."""
        sandbox = self._sandbox()
        if sandbox is None:
            return False
        try:
            from sandbox.sandbox_manager import SandboxTier
            if isinstance(tier, str):
                resolved = SandboxTier[tier.upper()]
            elif isinstance(tier, SandboxTier):
                resolved = tier
            else:
                return False
            sandbox.tier = resolved
            return True
        except Exception:
            return False

    def _assess_command(self, command: str) -> Dict[str, Any]:
        """Score a command via the risk scorer; returns {} when unavailable."""
        scorer = self._risk_scorer()
        if scorer is None:
            return {}
        try:
            assessment = scorer.assess(command)
            summary_fn = getattr(assessment, "summary", None)
            summary = summary_fn() if callable(summary_fn) else ""
            return {
                "score": getattr(assessment, "score", None),
                "blocked": getattr(assessment, "blocked", None),
                "summary": summary,
            }
        except Exception:
            return {}

    def _execute_command(self, command: str, workdir: Optional[str] = None) -> str:
        """Execute a command through the sandbox synchronously; "" on failure."""
        sandbox = self._sandbox()
        if sandbox is None:
            return ""
        try:
            return sandbox.execute(command, workdir)
        except Exception:
            return ""

    async def _stream_command(
        self, command: str, workdir: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream command output through the sandbox as chunks."""
        sandbox = self._sandbox()
        if sandbox is None:
            yield ""
            return
        try:
            async for chunk in sandbox.stream_execute(command, workdir):
                yield chunk
        except Exception as e:
            yield str(e)

    def _sandbox_stats(self) -> Dict[str, Any]:
        """Return a small status snapshot of the sandbox and risk scorer."""
        return {
            "tier": self._sandbox_tier(),
            "scorer_available": self._risk_scorer() is not None,
            "sandbox_available": self._sandbox() is not None,
        }
