"""V5Plugin — plugin lifecycle-hook integration for the V5 loop.

V5: on_session_end / pre_tool_call hooks via the plugin manager;
post_tool_call is owned by V5Control.

This mixin is intentionally dependency-free: it imports nothing from ``core``
(avoiding circular imports), so it can be mixed into ``NexusLoopV5`` safely.
Every attribute access is guarded — a plugin failure must never break the
loop, so hook firing is wrapped in try/except and introspection never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


class V5Plugin:
    """Plugin lifecycle-hook mixin with V5 for session hooks.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.kernel`` - may be None; has ``.plugins`` (a PluginManager with
      async ``trigger_hooks(event_name, *args, **kwargs)``) when present.
    - ``self.runtime`` - object with ``.hooks`` (a HookRegistry with async
      ``trigger(event, *args, **kwargs)``); may be None in exotic cases,
      everything is guarded.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    """

    def _plugin_manager(self) -> Any:
        """Return the kernel plugin manager, or None when unavailable."""
        try:
            kernel = getattr(self, "kernel", None)
            if kernel is None:
                return None
            return getattr(kernel, "plugins", None)
        except Exception:
            return None

    async def _trigger_plugin_hooks(self, event_name: str, *args, **kwargs) -> None:
        """Fire ``event_name`` through the plugin manager and runtime hooks.

        The kernel ``PluginManager`` is notified first, then the runtime
        ``HookRegistry`` (covering a plugin-style runtime registry). Both are
        wrapped in try/except that logs and continues — a failure here never
        breaks the loop.
        """
        plugins = self._plugin_manager()
        trigger_hooks = getattr(plugins, "trigger_hooks", None)
        if callable(trigger_hooks):
            try:
                await trigger_hooks(event_name, *args, **kwargs)
            except Exception as e:
                self.logger.warning(f"plugin hook {event_name} failed: {e}")

        hooks = getattr(getattr(self, "runtime", None), "hooks", None)
        trigger = getattr(hooks, "trigger", None)
        if callable(trigger):
            try:
                await trigger(event_name, *args, **kwargs)
            except Exception as e:
                self.logger.warning(f"runtime hook {event_name} failed: {e}")

    async def _fire_session_end_hooks(
        self, task_desc: str, messages: List[Dict[str, str]]
    ) -> None:
        """V5: fire on_session_end hooks at the end of a session.

        Mirrors the V1 loop: ``orchestrators/loop.py`` line 2893 fires
        ``trigger_hooks("on_session_end", task_desc, messages)`` in
        ``_finalize_session``. Fully guarded: never raises.
        """
        await self._trigger_plugin_hooks("on_session_end", task_desc, messages)

    def _enabled_plugin_names(self) -> List[str]:
        """Return names of enabled plugins, or [] when unavailable.

        Uses ``PluginManager.list_plugins()`` (filtering entries whose
        ``active`` flag is not False) with a fallback to the
        ``loaded_plugins`` collection. Never raises.
        """
        try:
            plugins = self._plugin_manager()
            if plugins is None:
                return []
            names: List[str] = []
            list_plugins = getattr(plugins, "list_plugins", None)
            if callable(list_plugins):
                for entry in list_plugins() or []:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name")
                    if name and entry.get("active", True) is not False:
                        names.append(str(name))
                if names:
                    return names
            loaded = getattr(plugins, "loaded_plugins", None)
            if callable(loaded):
                return [str(name) for name in (loaded() or {})]
            if isinstance(loaded, dict):
                return [str(name) for name in loaded]
            return []
        except Exception:
            return []
