import logging
import os
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

import requests

from tools.nexus_tools.result import ToolArgumentError, parse_tool_arguments

logger = logging.getLogger("NEXUS_PROVIDER")

class NexusBaseProvider(ABC):
    """
    NEXUS BASE PROVIDER SCHEMATIC 1.0
    Universal interface for all cloud and local model engines.
    """
    
    def __init__(self, provider_name: str, endpoint: str):
        self.provider_name = provider_name
        self.endpoint = endpoint
        self.model = ""
        self.api_key = ""
        self.headers = {}
        self.session = requests.Session()
        # Provider-reported token usage for the most recent request.  The
        # router copies this side-channel into the V5 result without changing
        # the long-standing provider.generate() text interface.
        self._last_usage: Optional[Dict[str, int]] = None
        # NEXUS providers use their configured endpoint directly. Inheriting
        # a stale machine-wide HTTP(S)_PROXY/ALL_PROXY setting can route cloud
        # calls through a dead localhost proxy and produce misleading local
        # provider errors. Proxy use remains opt-in via an explicit session or
        # provider implementation rather than an ambient process variable.
        self.session.trust_env = False
        self.thinking = False

        # Resolve provider metadata and secret references during construction.
        # Argument normalization below is deliberately a pure static helper.
        try:
            from configure.config_loader import NexusConfigLoader

            loader = NexusConfigLoader()
            config = loader.get_provider_config(provider_name)
            raw_key = config.get("api_key", "")
            if isinstance(raw_key, str) and raw_key.startswith("${") and raw_key.endswith("}"):
                raw_key = os.getenv(raw_key[2:-1], "")
            if not raw_key:
                raw_key = os.getenv(f"{provider_name.upper()}_API_KEY", "")
            self.api_key = raw_key
            self.model = config.get("model") or ""
            self.endpoint = config.get("endpoint") or self.endpoint
            if self.api_key and "YOUR_" in self.api_key:
                self.api_key = ""
        except Exception as e:
            logger.warning(f"[{provider_name.upper()}_INIT]: Failed to load config: {e}")

    @staticmethod
    def normalize_tool_arguments(raw: Any, *, tool_name: str = "") -> Dict[str, Any]:
        """Normalize provider tool arguments without silently dropping them.

        OpenAI-compatible providers often return arguments as a JSON string.
        Turning malformed JSON into ``{}`` makes a transport/protocol defect
        look like a normal missing-parameter call and causes the model loop to
        repeat the same bad request.  Preserve a bounded diagnostic envelope
        instead; the V5 loop turns it into a model-visible repair observation.
        """
        try:
            parsed = parse_tool_arguments(raw, tool_name=tool_name)
            return parsed if isinstance(parsed, dict) else {}
        except ToolArgumentError as exc:
            return {
                "__nexus_argument_error": str(exc)[:1000],
                "__nexus_raw_arguments": str(raw)[:4000],
            }

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled

    @staticmethod
    def request_timeout(kwargs: Optional[Dict[str, Any]], default: float) -> float:
        """Return a bounded per-request transport timeout.

        Router/V5 callers may provide a run-budget deadline through ``timeout``.
        Invalid or non-positive values fall back to the adapter default so a
        malformed model hint cannot disable transport protection.
        """
        try:
            value = float((kwargs or {}).get("timeout", default))
        except (TypeError, ValueError):
            value = float(default)
        if value <= 0:
            value = float(default)
        return max(0.001, value)

    @staticmethod
    def process_group_kwargs() -> Dict[str, Any]:
        """Return subprocess options that give the provider tree ownership."""
        if os.name == "nt":
            return {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200),
            }
        return {"start_new_session": True}

    @staticmethod
    def terminate_process_tree(process: Any, *, wait_timeout: float = 5.0) -> None:
        """Terminate and reap a CLI process and its owned descendants."""
        if process is None:
            return
        try:
            running = process.poll() is None
        except Exception:
            running = True
        if running:
            pid = getattr(process, "pid", None)
            tree_stopped = False
            try:
                if pid and os.name == "nt":
                    killer = subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        timeout=wait_timeout,
                        check=False,
                    )
                    tree_stopped = killer.returncode == 0
                elif pid:
                    os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                    tree_stopped = True
            except (OSError, subprocess.SubprocessError, ValueError):
                logger.debug("provider process-tree termination unavailable", exc_info=True)
            if not tree_stopped:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
        try:
            process.wait(timeout=wait_timeout)
        except (OSError, subprocess.SubprocessError, ProcessLookupError):
            logger.debug("provider process reap failed", exc_info=True)

    def reload_credentials(self, api_key: Optional[str] = None) -> bool:
        """Re-resolve the provider credential and rebuild auth headers.

        Reads the freshest key from the same env var / provider.yml reference
        used at construction, then swaps it into every auth header. Callers
        that already hold a fresher key (profile/OAuth resolution) can pass it
        explicitly to skip the config lookup. Never touches model/endpoint and
        never starts timers/threads — this is a pure, cheap re-read.
        """
        old_key = str(self.api_key or "")
        new_key = api_key
        if new_key is None:
            try:
                from configure.config_loader import NexusConfigLoader
                loader = NexusConfigLoader()
                config = loader.get_provider_config(self.provider_name)
                raw_key = str(config.get("api_key", "") or "")
                if raw_key.startswith("${") and raw_key.endswith("}"):
                    raw_key = os.getenv(raw_key[2:-1], "")
                if not raw_key:
                    raw_key = os.getenv(f"{self.provider_name.upper()}_API_KEY", "")
                new_key = raw_key
            except Exception as e:
                logger.warning(f"[{self.provider_name.upper()}_RELOAD]: failed to re-read config: {e}")
                new_key = old_key
        new_key = str(new_key or "").strip()
        if "YOUR_" in new_key:
            new_key = ""
        if new_key == old_key:
            return False
        self.api_key = new_key
        self._refresh_auth_headers(old_key)
        return True

    def _refresh_auth_headers(self, previous_key: str) -> None:
        """Swap the previous credential for the new one in every auth header.

        Handles both raw headers (``x-api-key``, ``x-goog-api-key``) and the
        common ``Authorization: Bearer ...`` form without knowing which header
        a concrete provider uses.
        """
        if not isinstance(self.headers, dict):
            return
        for name, value in list(self.headers.items()):
            if not isinstance(value, str):
                continue
            if value == f"Bearer {previous_key}":
                self.headers[name] = f"Bearer {self.api_key}"
            elif value == previous_key:
                self.headers[name] = str(self.api_key or "")


    @abstractmethod
    def generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        pass

    @abstractmethod
    def stream_generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        pass

    def _prepare_messages(self, prompt: str, system_prompt: str, messages: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        if messages:
            return messages
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

    def validate_api_key(self) -> bool:
        """Cheap credential presence check; network health is handled by router."""
        if self.provider_name in {"ollama", "lm_studio", "llama_cpp"}:
            return True
        key = (self.api_key or "").strip()
        return bool(key and "YOUR_" not in key and not key.startswith("sk-test"))

    def health_check(self, timeout: float = 8.0) -> Dict[str, Any]:
        """Non-invasive provider health metadata."""
        start = time.time()
        valid_key = self.validate_api_key()
        return {
            "provider": self.provider_name,
            "model": self.model,
            "endpoint": self.endpoint,
            "has_valid_key": valid_key,
            "latency_ms": round((time.time() - start) * 1000, 2),
            "healthy": valid_key,
        }
