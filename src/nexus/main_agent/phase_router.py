"""Phase-based model routing — different models for different loop phases.

Inspired by Devin Fusion and Gemini CLI: use a strong/expensive model for
planning and verification, and a cheaper/faster model for tool execution
and routine turns. This reduces cost and latency while maintaining quality
where it matters.

The router inspects the current phase and task characteristics to select
the optimal model. Configuration is via environment variables:

  NEXUS_PHASE_ROUTING=1                    # Enable phase routing
  NEXUS_MODEL_PLANNING=<model>             # Model for planning phases
  NEXUS_MODEL_EXECUTION=<model>            # Model for tool execution
  NEXUS_MODEL_VERIFICATION=<model>         # Model for verification
  NEXUS_MODEL_FALLBACK=<model>             # Model for everything else
  NEXUS_PLANNING_MAX_TOKENS=<int>          # Token budget for planning
  NEXUS_EXECUTION_MAX_TOKENS=<int>         # Token budget for execution
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PhaseModelConfig:
    """Model configuration for a specific phase."""
    model: str
    provider: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7


class PhaseModelRouter:
    """Routes different loop phases to different models.

    The router is stateless and reads configuration from environment variables
    at construction time. When phase routing is disabled (default), all phases
    use the default model unchanged.
    """

    def __init__(self):
        self.enabled = os.environ.get("NEXUS_PHASE_ROUTING", "").lower() in {
            "1", "true", "yes", "on",
        }
        self.planning = PhaseModelConfig(
            model=os.environ.get("NEXUS_MODEL_PLANNING", ""),
            max_tokens=int(os.environ.get("NEXUS_PLANNING_MAX_TOKENS", "4096") or 4096),
            temperature=0.3,  # Lower temperature for planning precision
        )
        self.execution = PhaseModelConfig(
            model=os.environ.get("NEXUS_MODEL_EXECUTION", ""),
            max_tokens=int(os.environ.get("NEXUS_EXECUTION_MAX_TOKENS", "2048") or 2048),
            temperature=0.5,
        )
        self.verification = PhaseModelConfig(
            model=os.environ.get("NEXUS_MODEL_VERIFICATION", ""),
            max_tokens=int(os.environ.get("NEXUS_VERIFICATION_MAX_TOKENS", "2048") or 2048),
            temperature=0.2,  # Very low for factual verification
        )
        self.fallback = PhaseModelConfig(
            model=os.environ.get("NEXUS_MODEL_FALLBACK", ""),
            max_tokens=4096,
            temperature=0.7,
        )
        if self.enabled:
            configured = sum(1 for c in [self.planning, self.execution, self.verification]
                           if c.model)
            logger.info(
                "phase-based model routing enabled (%d explicit phase models)", configured
            )

    def route(
        self,
        phase: str,
        *,
        default_model: str = "",
        default_provider: str = "",
        default_max_tokens: int = 4096,
    ) -> dict:
        """Select the model config for the given phase.

        Args:
            phase: Current loop phase (planning, execution, verification, etc.)
            default_model: Default model when routing is disabled or phase not configured.
            default_provider: Default provider.
            default_max_tokens: Default token budget.

        Returns:
            Dict with keys: model, provider, max_tokens, temperature
        """
        if not self.enabled:
            return {
                "model": default_model,
                "provider": default_provider,
                "max_tokens": default_max_tokens,
                "temperature": 0.7,
            }

        phase_lower = str(phase or "").lower()
        config = None

        if phase_lower in ("planning", "plan", "replan"):
            config = self.planning
        elif phase_lower in ("execution", "act", "tool", "tool_execution"):
            config = self.execution
        elif phase_lower in ("verification", "verify", "reflect"):
            config = self.verification
        else:
            config = self.fallback

        # Use configured model if available, otherwise fall back to default
        model = config.model if config.model else default_model
        provider = config.model and "" or default_provider  # Use default provider unless explicit

        return {
            "model": model,
            "provider": default_provider,
            "max_tokens": config.max_tokens or default_max_tokens,
            "temperature": config.temperature,
        }

    def thinking_budget(self, phase: str) -> int:
        """Return the thinking token budget for the phase.

        Planning and verification get more thinking budget; execution gets less.
        """
        if not self.enabled:
            return 0  # No thinking budget by default
        phase_lower = str(phase or "").lower()
        if phase_lower in ("planning", "plan", "replan"):
            return int(os.environ.get("NEXUS_PLANNING_THINKING_BUDGET", "2000") or 2000)
        if phase_lower in ("verification", "verify", "reflect"):
            return int(os.environ.get("NEXUS_VERIFICATION_THINKING_BUDGET", "1000") or 1000)
        return int(os.environ.get("NEXUS_EXECUTION_THINKING_BUDGET", "500") or 500)
