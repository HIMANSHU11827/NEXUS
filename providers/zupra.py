"""Zupra Local Provider — MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp
50M parameter model for fully offline local AI inference.
"""

import logging
import os
import time
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger("NEXUS_ZUPRA")

MODEL_ID = os.environ.get("NEXUS_PROVIDER_ZUPRA_MODEL", "MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp")


class ZupraProvider(NexusBaseProvider):
    """Local HuggingFace model provider for Zupra-1.6-50M.
    Fully offline, no API key needed. ~100MB RAM/disk.
    """

    def __init__(self):
        super().__init__("zupra", "local")
        self.model = MODEL_ID
        self._pipe = None
        self._loaded = False

    def _lazy_load(self):
        if self._loaded:
            return
        try:
            from transformers import pipeline
            logger.info(f"[ZUPRA] Loading {MODEL_ID}...")
            t0 = time.time()
            trust_remote = os.environ.get("NEXUS_TRUST_REMOTE_CODE", "0") == "1"
            if trust_remote:
                logger.warning("NEXUS_TRUST_REMOTE_CODE=1 — loading with custom model code")
            self._pipe = pipeline(
                "text-generation",
                model=MODEL_ID,
                trust_remote_code=trust_remote,
            )
            self._loaded = True
            logger.info(f"[ZUPRA] Loaded in {time.time()-t0:.1f}s")
        except Exception as e:
            logger.error(f"[ZUPRA] Failed to load: {e}")
            raise

    def generate(self, prompt: str = "", system_prompt: str = "",
                 messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        self._lazy_load()
        prepared = self._prepare_messages(prompt, system_prompt, messages)
        try:
            result = self._pipe(prepared, max_new_tokens=256, do_sample=True, temperature=0.7)
            return result[0]["generated_text"][-1]["content"] if isinstance(result, list) else str(result)
        except Exception as e:
            return f"Error: {e}"

    def stream_generate(self, prompt: str = "", system_prompt: str = "",
                        messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        self._lazy_load()
        prepared = self._prepare_messages(prompt, system_prompt, messages)
        try:
            result = self._pipe(prepared, max_new_tokens=256, do_sample=True, temperature=0.7)
            text = result[0]["generated_text"][-1]["content"] if isinstance(result, list) else str(result)
            yield text
        except Exception as e:
            yield f"Error: {e}"

    def validate_api_key(self) -> bool:
        return True
