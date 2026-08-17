# Nexus Settings map

This map is intentionally kept beside the Settings implementation. The registry in `settingsRegistry.ts` is the executable source of truth for navigation and search; this document records the page purpose and real data/action ownership so future Settings work does not collapse into a generic form.

| Page | Purpose | Primary implementation | Real data / actions |
| --- | --- | --- | --- |
| Theme & appearance | Visual preferences | `Appearance.tsx` | Browser `localStorage`, document theme classes |
| Notifications | Event alerts | `Notifications.tsx` | Browser permission plus device-local notification and sound preferences |
| Keyboard shortcuts | Command reference | `KeyboardShortcuts.tsx` | GUI shortcut documentation and modal navigation behavior |
| Workspace | Project context | `WorkspaceSettings.tsx` | Workspace root, directories, index, instructions, health APIs |
| Memory & context | Recall and retrieval | `Memory.tsx` | Memory stats/search, session history, export/import, clear |
| Safety | Policy guardrails | `SafetySettings.tsx` | Safety policies, presets, protected paths, diagnostics, save/reset |
| Providers | Model connections | `Providers.tsx` | Provider inventory, profiles, OAuth, runtime health, enable/disable |
| Voice | Speech runtime | `Voice.tsx` | Voice status, transcript/reply previews, start/stop/history/settings |
| Configuration | Runtime defaults | `ConfigurationPanel.tsx` | Model/provider/agent/session settings, sandbox, prompt, config files |
| Evolution | Self-improvement | `Evolution.tsx` | Evolution status, lifecycle, forges, enable/disable |
| Skills | Capability library | `SkillsManager.tsx` | Skill inventory, categories, enable/disable |
| Tools | Execution capabilities | `ToolsManager.tsx` | Tool registry, metadata, categories, enable/disable |
| Plugins | Extension lifecycle | `PluginManager.tsx` | Plugin inventory, trust/marketplace presentation, enable/disable |
| MCP | External tool servers | `McpManager.tsx` | MCP inventory, create/delete, enable/disable, server configuration |
| Hive | Agent orchestration | `HiveManager.tsx` | Hive runtime, personas, create/cancel/resume, enable/disable |
| Gateway | Messaging connections | `GatewayManager.tsx` | Gateway inventory, platform status, enable/disable, connection settings |
| Scheduled jobs | Recurring automation | `ScheduledJobsManager.tsx` | Job inventory, create/edit/delete/run, history and settings |
| Billing | Usage visibility | `Billing.tsx` | Reported local/runtime billing status and usage fields |
| About | System identity | `About.tsx` | Version, backend status, sessions, feature and diagnostic information |

## Navigation and state rules

- `SettingsPanel.tsx` owns the modal shell, focus trap, responsive navigation, page loading boundary, and cross-page refresh/error handling.
- Each page owns its domain interaction model and local editing state; pages should not be turned into a shared “title → cards → toggle” template.
- Settings search matches page name, group, purpose, and domain terms such as `api key`, `protected paths`, `transcription`, `MCP`, and `index`.
- Destructive or high-risk Settings actions remain explicit and preserve their existing confirmation/dirty-state behavior.
- Live status is only presented from backend/API data; local-only preferences are labeled as device-local.
