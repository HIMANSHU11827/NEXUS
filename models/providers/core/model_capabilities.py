"""Data-driven per-model capability & limit registry.

Capabilities are read from ``config/provider.yml`` so that context budgets,
output token caps and feature flags are per-model instead of one hardcoded
value applied to every model.

YAML shape (all optional)::

    model_capabilities:
      defaults:
        context_window: 8192
        max_output_tokens: 2048
        tools: false
        vision: false
        streaming: true
        structured_output: false
      providers:
        deepseek: {context_window: 65536, tools: true}
      models:
        "deepseek-chat": {context_window: 65536, max_output_tokens: 8192, tools: true}
        "deepseek-reasoner": {context_window: 65536, max_output_tokens: 8192}
        "*llama-3.3-70b*": {context_window: 131072, tools: true}
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Optional

logger = logging.getLogger("NEXUS_MODEL_CAPS")


@dataclass(frozen=True)
class ModelCapability:
    model: str = ""
    provider: str = ""
    context_window: int = 8192
    max_output_tokens: int = 2048
    tools: bool = False
    vision: bool = False
    streaming: bool = True
    structured_output: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def supports(self, *, tools: bool = False, vision: bool = False,
                 streaming: bool = False, structured_output: bool = False) -> bool:
        if tools and not self.tools:
            return False
        if vision and not self.vision:
            return False
        if streaming and not self.streaming:
            return False
        if structured_output and not self.structured_output:
            return False
        return True

    def clamp_max_tokens(self, requested: Optional[int]) -> int:
        """Clamp a caller-requested max output token count to this model's cap."""
        if not requested or int(requested) <= 0:
            return int(self.max_output_tokens)
        return int(min(int(requested), int(self.max_output_tokens)))


_FIELDS = {
    "context_window": int,
    "max_output_tokens": int,
    "tools": bool,
    "vision": bool,
    "streaming": bool,
    "structured_output": bool,
}

# Accepted aliases so existing provider.yml keys keep working.
_ALIASES = {
    "max_context": "context_window",
    "context": "context_window",
    "max_tokens": "max_output_tokens",
    "tool_calling": "tools",
    "stream": "streaming",
    "json_mode": "structured_output",
}


def _coerce(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    out: Dict[str, Any] = {}
    for raw_key, value in entry.items():
        key = _ALIASES.get(str(raw_key), str(raw_key))
        caster = _FIELDS.get(key)
        if caster is None:
            continue
        try:
            out[key] = caster(value)
        except (TypeError, ValueError):
            continue
    return out


class ModelCapabilityRegistry:
    """Resolves capabilities for a (provider, model) pair.

    Precedence: exact model entry > glob model entry > provider entry >
    global defaults.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}
        caps = config.get("model_capabilities") if isinstance(config, dict) else None
        caps = caps if isinstance(caps, dict) else {}
        self._defaults = _coerce(caps.get("defaults"))
        raw_providers = caps.get("providers") or {}
        raw_models = caps.get("models") or {}
        raw_providers = raw_providers if isinstance(raw_providers, dict) else {}
        raw_models = raw_models if isinstance(raw_models, dict) else {}
        self._providers = {str(k).lower(): _coerce(v) for k, v in raw_providers.items()}
        self._models = {str(k): _coerce(v) for k, v in raw_models.items()}
        # per-provider max_tokens defined in providers.<id>.max_tokens
        provider_section = config.get("providers") if isinstance(config, dict) else None
        if isinstance(provider_section, dict):
            for pid, pcfg in provider_section.items():
                if not isinstance(pcfg, dict):
                    continue
                extra = _coerce({k: v for k, v in pcfg.items() if k in _ALIASES or k in _FIELDS})
                if extra:
                    merged = dict(self._providers.get(str(pid).lower(), {}))
                    # explicit model_capabilities entries win over provider block
                    extra.update(merged)
                    self._providers[str(pid).lower()] = extra

    @classmethod
    def from_loader(cls, loader: Any = None) -> "ModelCapabilityRegistry":
        try:
            if loader is None:
                from configure.config_loader import NexusConfigLoader
                loader = NexusConfigLoader()
            cfg = loader.get("provider", {}) or {}
        except Exception:
            logger.warning("ModelCapabilityRegistry: falling back to built-in defaults", exc_info=True)
            cfg = {}
        return cls(cfg if isinstance(cfg, dict) else {})

    def _model_overrides(self, model: str) -> Dict[str, Any]:
        model = str(model or "")
        if not model:
            return {}
        if model in self._models:
            return self._models[model]
        # longest matching glob wins (most specific pattern)
        matches = [(len(pat), ov) for pat, ov in self._models.items()
                   if any(ch in pat for ch in "*?[") and fnmatch.fnmatch(model, pat)]
        if matches:
            matches.sort(key=lambda item: item[0], reverse=True)
            return matches[0][1]
        return {}

    def get(self, provider_id: str = "", model: str = "") -> ModelCapability:
        merged: Dict[str, Any] = {}
        merged.update(self._defaults)
        merged.update(self._providers.get(str(provider_id or "").lower(), {}))
        merged.update(self._model_overrides(model))
        base = ModelCapability(model=str(model or ""), provider=str(provider_id or ""))
        return replace(base, **merged) if merged else base

    def known_models(self) -> Dict[str, Dict[str, Any]]:
        return {m: dict(v) for m, v in self._models.items()}
