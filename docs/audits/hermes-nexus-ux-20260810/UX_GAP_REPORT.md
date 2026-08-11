# Hermes vs Nexus UX Gap Report

Date: 2026-08-10
Scope: provider setup, model switching, fallback visibility, settings entry points, sandbox controls, and failure recovery.

## Evidence captured

The audit captured the local Nexus GUI at `http://127.0.0.1:5173/` in four states:

1. [Nexus home, backend unavailable](./01-nexus-home.png) — the composer is disabled and the placeholder says to start `python -m nexus --server`.
2. [Nexus settings](./02-nexus-settings.png) — settings are grouped into Personal, Workspace, Runtime, Extensions, Automation, and System; the footer reports “Backend unavailable.”
3. [Nexus Providers, backend unavailable](./03-nexus-providers.png) — the provider section shows “Internal Server Error” with only “Try again.”
4. [Nexus Providers, backend connected](./04-nexus-providers-connected.png) — the footer reports “Backend connected,” but the provider section reports “Not authenticated.”

Read-only TUI checks also ran:

- `npx.cmd tsx tui/nexus-tui-headless.ts help` lists provider commands (`providers`, `provider`, `model`) and sandbox controls.
- `npx.cmd tsx tui/nexus-tui-headless.ts providers` returned `Not authenticated`.

The Hermes reference was read from the checked-out source at `external/hermes-agent` and its local website docs. The clearest provider UX contract is in `website/docs/integrations/providers.md`: `hermes model` is the full setup wizard; `/model` only switches among already-configured providers/models. The README also puts `hermes model`, `hermes setup`, and `hermes doctor` in the first-run command path.

## Flow findings

### Step 1 — Start and understand the runtime

Health: good visual hierarchy, incomplete recovery guidance.

- Nexus makes the local-first model clear and shows the exact backend start command in the composer.
- The disabled composer gives no direct action to start or diagnose the backend.
- Hermes documents a compact first-run sequence (`hermes setup`, `hermes model`, `hermes doctor`) before the user enters a chat.

### Step 2 — Open settings

Health: strong organization, high surface area.

- Nexus’s settings taxonomy is easy to scan and includes Provider, Configuration, Safety, Memory, and MCP in one control center.
- The large number of sections increases the need for consistent per-section loading and error states.
- The settings shell correctly exposes backend availability, but that status is not enough to explain authentication state.

### Step 3 — Configure providers

Health: blocked in the captured environment; failure copy is not actionable.

- When the API is unavailable, the user sees `Internal Server Error` rather than a start/health/configuration path.
- When the API is reachable, the user sees `Not authenticated`; the screen does not say which credential is missing, where `NEXUS_DASHBOARD_TOKEN` belongs, or whether provider API keys can be configured through the TUI/config file instead.
- The GUI source supports profiles, custom OpenAI-compatible endpoints, API-key fields, OAuth sign-in, and active-runtime reachability, but none of those affordances are reachable until the provider inventory request authenticates.

### Step 4 — Switch model/provider and understand fallback

Health: capability exists, mental model is fragmented.

- Nexus offers `/provider`, `/providers`, `/model`, `/config`, and GUI Providers/Configuration surfaces. The TUI reference describes management actions, but the live headless command stops at authentication.
- The captured UI does not show the active fallback chain, cooldown state, last failed provider, or why a fallback occurred.
- Hermes explicitly separates setup from switching and documents provider/model syntax and custom endpoint behavior. This is a clearer mental model for users.

### Step 5 — Choose sandbox and permissions

Health: discoverable and visibly separate.

- Nexus exposes Permission mode and Command sandbox as separate composer controls, with `No Sandbox`, `Sandbox`, and `Advanced Sandbox` visible together.
- The TUI reference also exposes `/sandbox` and `/permissions` separately.
- This is a relative Nexus strength; the remaining UX need is explaining the safety consequence of each tier at the point of choice.

## Highest-impact gaps

1. **Authentication error is not recoverable from the screen.** “Not authenticated” is technically accurate but gives no next action. The same problem appears in the GUI and TUI.
2. **Provider setup versus provider switching is not unified.** Nexus has multiple entry points without a documented canonical path comparable to Hermes’s `hermes model` versus `/model` distinction.
3. **Fallback is operationally opaque.** Nexus now records provider attempts and evidence internally, but the user-facing settings/provider surfaces do not expose fallback order, cooldown, or the reason for the selected provider.
4. **Backend availability and authentication are conflated in the journey.** The GUI footer can say “Backend connected” while the provider section is unusable because auth failed.

## Safe small improvement

The safe immediate improvement is documentation, not a runtime/UI change: document the canonical Nexus startup/auth path and explicitly distinguish provider setup from switching. That note was added to `docs/GUI_ARCHITECTURE.md` under “Provider setup and troubleshooting.”

## Limits

- The audit did not submit credentials, run OAuth, add providers, change models, toggle sandbox tiers, or alter runtime configuration.
- The GUI provider inventory could not be reached because the local server rejected the unauthenticated request; provider rows and fallback controls were therefore assessed from source plus the error state, not from a connected provider list.
- TUI visual layout was not screenshot-captured in this run; TUI findings are based on its documented command surface and a read-only headless help/provider invocation.
- Screenshots alone cannot establish keyboard navigation, screen-reader semantics, contrast ratios, or focus restoration; those remain follow-up checks.
