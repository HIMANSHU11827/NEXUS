"""Compatibility facade for hybrid model routing.

The original ``MixtureOfArchitects`` object returned an empty OpenAI-shaped
response and silently discarded the user's request.  Provider selection and
fallback already live in :class:`NexusMoERouter`, so this layer delegates to
that authoritative router instead of pretending to run an unimplemented
multi-architect ensemble.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NEXUS_MOA")


class MixtureOfArchitects:
    """Route hybrid requests through the configured MoE provider mesh."""

    def __init__(self, base_router: Any):
        self.base_router = base_router
        logger.info("MixtureOfArchitects ready; delegating to provider mesh")

    @staticmethod
    def _as_text(result: Any) -> str:
        """Normalize legacy provider-shaped responses without fake success."""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            choices = result.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict) and message.get("content") is not None:
                    return str(message["content"])
            if result.get("error"):
                return f"[MOA_ERROR]: {result['error']}"
        return str(result or "")

    def aggregate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        """Return one truthful response from the configured provider mesh.

        ``aggregate`` remains the legacy public name.  It is intentionally a
        delegating facade until Nexus has a real multi-model ensemble policy;
        it must never return an empty successful response.
        """
        router = self.base_router
        generate = getattr(router, "generate", None)
        if not callable(generate):
            return "[MOA_ERROR]: provider mesh is unavailable"
        try:
            result = generate(messages=list(messages or []), **kwargs)
            text = self._as_text(result)
            return text or "[MOA_ERROR]: provider mesh returned an empty response"
        except Exception as exc:
            logger.warning("Hybrid provider mesh failed: %s", exc)
            return f"[MOA_ERROR]: {exc}"
