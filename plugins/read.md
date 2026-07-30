# Plugins

Plugin architecture — extensible modules with lifecycle hooks, tool registration, and trust model.

**Version:** 2.0.0

## Status
Beta. Plugin forge exists in `evolution/plugin_forge/` for creation and refinement.

## Runtime Lifecycle
- `PluginManager` (ThreadSafeSingleton) — discover, load, unload plugins from bundled + user paths
- `PluginContext` — register_tool(), register_hook(), register_cli_command() exposed to plugins
- `HookRegistry` — event-driven lifecycle hooks (pre/post tool call, session events)
- `PluginToolAdapter` — wraps plugin handlers as BaseTool-compatible with streaming support
- `trust.py` — PluginInstallDisabled, require_unverified_install_opt_in(), path-based bundled checks
- User plugin source remains opt-in; disabled plugins discoverable but not executed
