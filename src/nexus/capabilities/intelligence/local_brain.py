"""Local-provider adapter used by the optional local-brain optimization."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")


class NexusLocalBrain:
    """Use configured local providers without silently falling back to cloud."""

    DEFAULT_PROVIDERS = ("lm_studio", "ollama", "llama_cpp", "zupra")

    def __init__(self, root: str):
        self.root = root
        self._factory = None
        self._providers: Dict[str, Any] = {}
        logger.info("NexusLocalBrain ready; local provider loading is lazy")

    def _provider_factory(self):
        if self._factory is None:
            from models.providers.core.factory import NexusProviderFactory
            self._factory = NexusProviderFactory()
        return self._factory

    def _candidate_names(self, requested: Optional[str] = None) -> List[str]:
        selected = str(requested or os.environ.get("NEXUS_LOCAL_PROVIDER", "")).strip()
        if selected:
            return [selected]
        return list(self.DEFAULT_PROVIDERS)

    def _provider(self, name: str) -> Any:
        if name not in self._providers:
            provider = self._provider_factory().get_provider_by_name("local", name)
            if provider is not None:
                self._providers[name] = provider
        return self._providers.get(name)

    @staticmethod
    def _failed(text: Any) -> bool:
        value = str(text or "").strip().lower()
        return not value or value.startswith(("error", "[provider_error]", "[local_brain_error]"))

    def generate(
        self,
        prompt: str = "",
        system_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        """Generate through the first responding local provider."""
        requested = kwargs.pop("provider", None)
        failures: List[str] = []
        for name in self._candidate_names(requested):
            provider = self._provider(name)
            if provider is None:
                failures.append(f"{name}: unavailable")
                continue
            try:
                result = provider.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    messages=messages,
                    **kwargs,
                )
                if not self._failed(result):
                    return str(result)
                failures.append(f"{name}: {str(result)[:160]}")
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        detail = "; ".join(failures) or "no local providers configured"
        return f"[LOCAL_BRAIN_ERROR]: {detail}"

    def stream_generate(
        self,
        prompt: str = "",
        system_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream from the first local provider with a non-error response."""
        requested = kwargs.pop("provider", None)
        failures: List[str] = []
        for name in self._candidate_names(requested):
            provider = self._provider(name)
            if provider is None:
                failures.append(f"{name}: unavailable")
                continue
            try:
                parts = list(provider.stream_generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    messages=messages,
                    **kwargs,
                ))
                result = "".join(str(part or "") for part in parts)
                if not self._failed(result):
                    yield from (str(part) for part in parts if part)
                    return
                failures.append(f"{name}: {result[:160]}")
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        detail = "; ".join(failures) or "no local providers configured"
        yield f"[LOCAL_BRAIN_ERROR]: {detail}"

    def scan_image(self, path: str) -> str:
        """Fail truthfully until a configured local vision provider is available."""
        return (
            "[LOCAL_BRAIN_ERROR]: image scanning requires a configured local "
            f"vision provider; no image inference was performed for {path}"
        )
