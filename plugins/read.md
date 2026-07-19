# Plugins

Plugin architecture and plugin registry — extensible modules that add functionality to the core platform.

**Version:** 1.0.0

## Status
Early stage. Plugin forge exists in `evolution/plugin_forge/` for creation and refinement.

## Runtime Lifecycle
- Plugins register tools through `PluginContext.register_tool()`.
- Plugins register lifecycle hooks through `PluginContext.register_hook()`.
- `PluginManager.unload_plugin(name)` removes tools and hooks owned by that plugin before dropping the loaded context.
- Plugin metadata with `active: false` is respected by the runtime loader; disabled plugins are discoverable but not executed.
- User plugin source remains opt-in because plugins are executable Python code.
