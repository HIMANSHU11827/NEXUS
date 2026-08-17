"""V5Config — configuration access for the V5 loop. Wraps config.NexusConfigLoader: typed getters, provider configs, directory helpers, reload, and runtime seeding."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class V5Config:
    """Mixin giving the V5 loop access to the repo-wide config system.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.runtime`` - runtime dataclass duck-typed to carry
      ``permission_policy`` / ``sandbox_tier``; fields are optional and all
      writes are guarded with ``hasattr``/``setattr`` so the loop survives
      exotic runtimes.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self.session_id`` - id used as fallback run id for emitted events.

    This mixin is intentionally dependency-free: it imports nothing from
    ``orchestrators.v5`` (lazy import of ``NexusConfigLoader`` inside the
    method) and never raises, so the loop can always start.
    """

    def _config_loader(self) -> Optional[Any]:
        """Return the cached ``NexusConfigLoader`` singleton, or None on failure.

        The import happens lazily inside the method to avoid circular
        imports; the loader is cached on ``self._v5_config_loader``.
        """
        cached = getattr(self, "_v5_config_loader", None)
        if cached is not None:
            return cached
        try:
            from configure.config_loader import NexusConfigLoader

            loader = NexusConfigLoader()
            self._v5_config_loader = loader
            return loader
        except Exception as e:
            logger.debug(f"[V5CONFIG] config loader unavailable: {e}")
            self._v5_config_loader = None
            return None

    def _config(self, key: str, default: Any = None) -> Any:
        """Return a config value by key, or ``default`` on any failure."""
        loader = self._config_loader()
        if loader is None:
            return default
        try:
            return loader.get(key, default)
        except Exception as e:
            logger.debug(f"[V5CONFIG] get '{key}' failed: {e}")
            return default

    def _config_system(self, key: str, default: Any = None) -> Any:
        """Return a system config value, or ``default`` on any failure."""
        loader = self._config_loader()
        if loader is None:
            return default
        try:
            return loader.get_system(key, default)
        except Exception as e:
            logger.debug(f"[V5CONFIG] get_system '{key}' failed: {e}")
            return default

    def _config_data(self) -> Dict[str, Any]:
        """Return the full loaded config mapping, or {} on failure."""
        loader = self._config_loader()
        if loader is None:
            return {}
        try:
            raw = loader.data
            if callable(raw):
                raw = raw()
            return dict(raw) if isinstance(raw, dict) else {}
        except Exception as e:
            logger.debug(f"[V5CONFIG] data() failed: {e}")
            return {}

    def _config_reload(self) -> bool:
        """Reload config files from disk; True on success, False on failure."""
        loader = self._config_loader()
        if loader is None:
            return False
        try:
            loader.reload()
            return True
        except Exception as e:
            logger.debug(f"[V5CONFIG] reload failed: {e}")
            return False

    def _provider_config(self, name: str) -> Dict[str, Any]:
        """Return the merged provider config for ``name``, or {} on failure."""
        loader = self._config_loader()
        if loader is None:
            return {}
        try:
            raw = loader.get_provider_config(name)
            return dict(raw) if isinstance(raw, dict) else {}
        except Exception as e:
            logger.debug(f"[V5CONFIG] provider '{name}' config failed: {e}")
            return {}

    def _config_dirs(self) -> Dict[str, str]:
        """Resolve config/root/memory/knowledge directories; "" each on failure."""
        loader = self._config_loader()
        dirs: Dict[str, str] = {}
        try:
            dirs["config_dir"] = str(loader.get_config_dir()) if loader is not None else ""
        except Exception:
            dirs["config_dir"] = ""
        try:
            dirs["root"] = str(loader.get_root()) if loader is not None else ""
        except Exception:
            dirs["root"] = ""
        try:
            dirs["memory_dir"] = str(loader.get_memory_dir()) if loader is not None else ""
        except Exception:
            dirs["memory_dir"] = ""
        try:
            dirs["knowledge_dir"] = str(loader.get_knowledge_dir()) if loader is not None else ""
        except Exception:
            dirs["knowledge_dir"] = ""
        return dirs

    def _init_config(self) -> None:
        """Wire the config system once at loop start: seed runtime fields."""
        loader = self._config_loader()
        if loader is None:
            logger.debug("[V5CONFIG] loader unavailable; skipping init")
            return
        try:
            self._apply_config_settings()
        except Exception as e:
            logger.warning(f"[V5CONFIG] failed to apply config settings: {e}")
        try:
            data = self._config_data()
        except Exception:
            data = {}
        logger.info("[V5CONFIG] configuration loaded (%s keys)", len(data) or 0)

    def _apply_config_settings(self) -> None:
        """Seed runtime fields from configure; documented extension point, never raises.

        Reads ``permissions.mode`` and ``sandbox.tier`` via ``_config`` and
        applies them to ``self.runtime.permission_policy`` /
        ``self.runtime.sandbox_tier`` when those attributes exist AND the
        loaded value is a non-empty string. No-ops when keys are absent or
        the runtime lacks the fields.
        """
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            return
        mappings = (
            ("permissions.mode", "permission_policy"),
            ("sandbox.tier", "sandbox_tier"),
        )
        for key, attr in mappings:
            try:
                if not hasattr(runtime, attr):
                    continue
                value = self._config(key)
                if not isinstance(value, str) or not value:
                    continue
                setattr(runtime, attr, value)
                logger.debug("[V5CONFIG] applied %s -> runtime.%s", key, attr)
            except Exception as e:
                logger.debug(f"[V5CONFIG] failed to apply {key}: {e}")
