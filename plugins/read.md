# Plugins

Plugin architecture — extensible modules with a full lifecycle, lifecycle hooks, tool registration, capability gating, fault isolation, and trust model.

**Version:** 3.0.0

## Status
Beta. Plugin forge exists in `evolution/plugin_forge/` for creation and refinement.

## Runtime Lifecycle
A plugin is tracked through explicit stages on a `PluginRecord`:
`discovered → validated → loading → loaded → initialized → enabled → disabled → uninstalled` (plus `failed`).

- `PluginManager` (ThreadSafeSingleton) — discover, validate, load, enable, disable, uninstall plugins from bundled + user paths
- `PluginRecord` — per-plugin lifecycle stage, capabilities, fault history, and registered-artifact audit
- `PluginContext` — `register_tool()`, `register_hook()`, `register_cli_command()` exposed to plugins (capability-gated)
- `HookRegistry` — event-driven lifecycle hooks (pre/post tool call, session events), individually fault-isolated
- `PluginToolAdapter` — wraps plugin handlers as BaseTool-compatible with streaming support
- `trust.py` — `PluginInstallDisabled`, `require_unverified_install_opt_in()`, path-based bundled checks, capability resolution

## State & Persistence
- Lifecycle state persists to `~/.nexus/plugins/state.json` (stdlib, atomic write via temp + `os.replace`, never raises).
- Persisted state is applied only when the plugin's fingerprint (source + dir + version + capabilities) matches, so stale state never leaks across a rewritten or renamed plugin.
- `enable`/`disable`/`uninstall` fully remove the plugin's registered tools, hooks, and CLI commands from the live registries.

## Fault Isolation
- Every plugin action (load / init / run hook / tool) is individually `try/except`'d — a crashing plugin never kills the core and never blocks other plugins from loading.
- A plugin that errors three times consecutively during a session is auto-disabled with reason `crash_loop` and that state is recorded.

## Trust / Capabilities
- No unrestricted default. Each plugin declares a capability allowlist (from its metadata manifest, e.g. `tools`, `hooks`, `cli`, `network`, `files`, `mcp`).
- `PluginRecord.capabilities` gates registration: a plugin trying to register a tool/hook/command for a capability it was not granted is denied at the registration boundary.
- Plugins without an explicit list get the legacy in-process surface (`tools`/`hooks`/`cli`) only; external capabilities (`network`/`files`/`mcp`) stay denied.
- User plugin source remains opt-in; disabled plugins discoverable but not executed.

## Hook Block Returns
- `pre_tool_call`-style hooks that return `{"action": "block"}` or `{"block": True}` are surfaced as a structured `{"action": "block", "reason": ...}` decision so callers (e.g. orchestrators/v5) can honor them instead of discarding the veto.
- Non-block hook returns pass through unchanged for backward compatibility.

## Dependency Isolation
- Plugin imports stay lazy and per-plugin; no third-party dependency is imported at module top of `plugins/`.
- A plugin missing a dependency fails that plugin only.