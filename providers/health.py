"""Provider health, capability, and latency tracking."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from providers.reliability import classify_failure, redact_secrets

# A provider marked unhealthy is excluded from the mesh only for this long;
# without a decay window a single transient failure banned it permanently.
DEGRADED_TTL_SECONDS = 60.0


@dataclass
class ProviderCapability:
    text: bool = True
    streaming: bool = True
    vision: bool = False
    local: bool = False
    tool_calling: bool = False
    max_context: int = 0


@dataclass
class ProviderHealth:
    provider_id: str
    healthy: bool
    latency_ms: Optional[float] = None
    last_error: str = ""
    checked_at: float = field(default_factory=time.time)
    capability: ProviderCapability = field(default_factory=ProviderCapability)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["capability"] = asdict(self.capability)
        return data


class ProviderHealthRegistry:
    """In-memory provider telemetry with normalized errors."""

    def __init__(self) -> None:
        self._health: Dict[str, ProviderHealth] = {}

    def mark_success(self, provider_id: str, latency_ms: float, capability: Optional[ProviderCapability] = None) -> None:
        self._health[provider_id] = ProviderHealth(
            provider_id=provider_id,
            healthy=True,
            latency_ms=latency_ms,
            capability=capability or self._health.get(provider_id, ProviderHealth(provider_id, True)).capability,
        )

    def mark_failure(self, provider_id: str, error: Exception | str, capability: Optional[ProviderCapability] = None) -> None:
        self._health[provider_id] = ProviderHealth(
            provider_id=provider_id,
            healthy=False,
            last_error=self.normalize_error(error),
            capability=capability or self._health.get(provider_id, ProviderHealth(provider_id, False)).capability,
        )

    def get(self, provider_id: str) -> Optional[ProviderHealth]:
        return self._health.get(provider_id)

    def all(self) -> List[Dict[str, Any]]:
        return [h.to_dict() for h in self._health.values()]

    def is_degraded(self, provider_id: str) -> bool:
        health = self._health.get(provider_id)
        if not health or health.healthy:
            return False
        return (time.time() - health.checked_at) < DEGRADED_TTL_SECONDS

    @staticmethod
    def normalize_error(error: Exception | str) -> str:
        """Classify and redact. Never returns raw credential material."""
        classification = classify_failure(
            error if isinstance(error, BaseException) else None,
            body=None if isinstance(error, BaseException) else error,
        )
        detail = redact_secrets(classification.message)[:400]
        return f"{classification.failure_class.value.upper()}: {detail}" if detail \
            else classification.failure_class.value.upper()


class ProviderCapabilityRegistry:
    """Static model/provider capability registry used by the router.

    It is intentionally conservative. Unknown providers are treated as text
    providers with no tool/vision claim until proven otherwise.
    """

    DEFAULTS: Dict[str, ProviderCapability] = {
        "openrouter": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "openai": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=128000),
        "anthropic": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=200000),
        "gemini": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=1000000),
        "groq": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=131000),
        "mistral": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "qwen": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "deepseek": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "perplexity": ProviderCapability(text=True, streaming=True, tool_calling=False, max_context=128000),
        "ollama": ProviderCapability(text=True, streaming=True, local=True, max_context=32000),
        "lm_studio": ProviderCapability(text=True, streaming=True, local=True, max_context=32000),
        "llama_cpp": ProviderCapability(text=True, streaming=True, local=True, max_context=32000),
        "vlm": ProviderCapability(text=True, streaming=False, vision=True, max_context=128000),
    }

    def get(self, provider_id: str) -> ProviderCapability:
        return self.DEFAULTS.get(str(provider_id or "").lower(), ProviderCapability())

    def supports(self, provider_id: str, *, streaming: bool = False, vision: bool = False, local: Optional[bool] = None) -> bool:
        capability = self.get(provider_id)
        if streaming and not capability.streaming:
            return False
        if vision and not capability.vision:
            return False
        if local is not None and capability.local != local:
            return False
        return capability.text

    def choose(
        self,
        candidates: List[str],
        health: ProviderHealthRegistry,
        *,
        streaming: bool = False,
        vision: bool = False,
        prefer_local: bool = False,
    ) -> List[str]:
        viable = [
            c for c in candidates
            if self.supports(c, streaming=streaming, vision=vision)
            and not health.is_degraded(c)
        ]
        if prefer_local:
            viable.sort(key=lambda c: (not self.get(c).local, -self.get(c).max_context))
        else:
            viable.sort(key=lambda c: (self.get(c).local, -self.get(c).max_context))
        return viable
