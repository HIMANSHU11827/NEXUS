# NEXUS Profiles + Isolated Config System

## Status: ARCHITECTURE v1.0 — Design Document (Historical)
## Date: 2026-05-21
## Author: NEXUS Evolution Council — Architect

> _(Historical design proposal. The current config system uses `config/config_loader.py` (NexusConfigLoader singleton), `config/profiles.py` (profile CRUD), and `config/provider.yml`. The proposed `hive/profiles/` and `core/schema/` structures were not implemented as described.)_

---

## 1. Executive Summary

NEXUS currently has a **single monolithic configuration** (`configs/nexus_config.yaml`) loaded by two conflicting loaders (`core/config_loader.py` and `core/config.py`). There is **no profile system** — every run uses the same provider, same tools, same memory settings. API keys are embedded in YAML alongside configuration.

This design introduces **named profiles** with **isolated config files**, **profile inheritance**, **secrets separation**, and **runtime profile switching**. The six NEXUS Evolution Council agents (Architect, Researcher, Planner, Coder, Debugger, Reviewer) each get their own profile, but the system is generic — any number of profiles can exist.

---

## 2. Current Problems

| Problem | Impact |
|---------|--------|
| Two competing config loaders (`NexusConfig`, `NexusConfigLoader`) | Ambiguous authority, wasted bytes |
| API keys in YAML alongside settings | Accidental commits, no secrets isolation |
| No profiles | Cannot run different agents with different providers/tools |
| No schema validation | Typos and invalid values pass silently |
| No config versioning | Breaking changes have no migration path |
| All env vars in one `.env` | Profile-specific secrets mix together |

---

## 3. System Architecture

### 3.1 Directory Layout

```
nexus_root/
├── hive/profiles/                          # NEW: Profile definitions
│   ├── base/                          # Base profile (everything inherits from this)
│   │   ├── config.yaml                # Default settings
│   │   └── .env                       # Base secrets (template)
│   ├── default/                       # Default active profile
│   │   ├── config.yaml                # Inherits from base, overrides only
│   │   ├── .env                       # Default profile secrets
│   │   └── profile.yaml               # Profile metadata (inherits: base)
│   ├── architect/                     # Council: Architect agent
│   │   ├── config.yaml
│   │   ├── .env
│   │   └── profile.yaml
│   ├── researcher/
│   │   ├── config.yaml
│   │   ├── .env
│   │   └── profile.yaml
│   ├── planner/
│   │   ├── config.yaml
│   │   ├── .env
│   │   └── profile.yaml
│   ├── coder/
│   │   ├── config.yaml
│   │   ├── .env
│   │   └── profile.yaml
│   ├── debugger/
│   │   ├── config.yaml
│   │   ├── .env
│   │   └── profile.yaml
│   └── reviewer/
│       ├── config.yaml
│       ├── .env
│       └── profile.yaml
├── configs/
│   ├── nexus_config.yaml              # LEGACY — will be migrated
│   └── profiles.yaml                  # Registry of known profiles + active selector
└── core/
    ├── config.py                      # REWRITTEN — thin wrapper delegating to profile system
    ├── config_loader.py               # REWRITTEN — now a ProfilesManager
    └── schema/
        ├── __init__.py
        ├── profile.py                 # Pydantic model for profile.yaml
        └── settings.py                # Pydantic model for config.yaml
```

### 3.2 File Purposes

| File | Purpose |
|------|---------|
| `hive/profiles/base/config.yaml` | Ground truth defaults — all profiles inherit from here |
| `hive/profiles/base/.env` | API key templates (the `YOUR_*` placeholders) |
| `hive/profiles/<name>/profile.yaml` | Profile metadata: `{name, inherits, description, tags, active}` |
| `hive/profiles/<name>/config.yaml` | Profile-specific overrides (inherit from base, override only what differs) |
| `configs/profiles.yaml` | Profile registry — maps profile names to paths, sets active profile |
| `core/config_loader.py` | Rewritten as the single `ProfilesManager` — loads, validates, switches |

### 3.3 Inheritance Rules

```
base config.yaml  ←  default/profile.yaml → overrides
                  ←  architect/profile.yaml → overrides
                  ←  researcher/profile.yaml → overrides
                  ...
```

- `base` is the root. Never modified by user profiles.
- Each profile has `inherits: base` in its `profile.yaml`.
- Config merge = deep merge. Lists are replaced (not merged). Scalars override.
- Future: multi-level inheritance (`inherits: [base, my-custom-base]`).

---

## 4. Component Design

### 4.1 ProfilesManager (core/config_loader.py — rewritten)

```python
class ProfilesManager(ThreadSafeSingleton):
    """
    Single entry point for all NEXUS configuration.
    Replaces both NexusConfig and NexusConfigLoader.
    
    Features:
    - Named profile management
    - Profile inheritance (deep merge from base)
    - Per-profile .env loading (secrets isolation)
    - Pydantic validation
    - Runtime profile switching
    - API: get(), get_profile(), list_profiles(), switch_profile()
    """
```

**API Surface:**

| Method | Returns | Purpose |
|--------|---------|---------|
| `get(path, default=None)` | Any | Dot-notation config access (same API as existing) |
| `get_profile(name)` | ProfileInfo | Metadata for a named profile |
| `active_profile` | str | Currently active profile name |
| `list_profiles()` | List[str] | All known profile names |
| `switch_profile(name)` | bool | Change active profile at runtime |
| `validate_profile(name)` | List[str] | Validate a profile's config, return warnings |
| `reload()` | None | Re-read all config files |
| `get_system(key)` | Any | Shortcut for `get("system.{key}")` — backward compat |
| `get_security(key)` | Any | Shortcut for `get("security.{key}")` |
| `get_active_providers()` | List[str] | Active providers for current profile |
| `get_provider_config(name)` | dict | Provider settings for current profile |

### 4.2 Config Schema (core/schema/)

**profile.py:**
```python
@dataclass
class ProfileMeta:
    name: str
    inherits: str = "base"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)  # if empty, all enabled
    disabled_tools: list[str] = field(default_factory=list)
    active_skills: list[str] = field(default_factory=list)
    disabled_skills: list[str] = field(default_factory=list)
    memory_persistence: str = "atomic_checkpoints"
    vault_mode: str = "gravity_rag"
    safety_strictness: float = 0.8
```

**settings.py — full typed config model:**
```python
@dataclass
class SystemSettings:
    kernel_mode: str = "recursive_frontier"
    default_provider: str = "local"
    provider_name: str = "SOVEREIGN_BRAIN"
    brain_mode: str = "AUTO"
    shell: str = "ghost_v1"
    branding: str = "🦀"
    workspace_root: str = "./workspace"
    log_level: str = "INFO"

@dataclass
class SecuritySettings:
    safety_strictness: float = 0.8
    prover_gate_active: bool = False
    sandbox_mode: str = "firecracker_ev"

@dataclass
class MemorySettings:
    persistence: str = "atomic_checkpoints"
    vault_mode: str = "gravity_rag"

@dataclass
class ProviderEntry:
    active: bool = False
    api_key: str = ""      # loaded from .env, never stored in YAML
    model: str = ""
    endpoint: str = ""
    ctx_size: int = 4096
    gpu_layers: int = -1
    main_gpu: int = 0
    deployment: str = ""
    parent_provider: str = ""

@dataclass
class VoiceSettings:
    enabled: bool = False
    auto_speak: bool = True
    ...  # matches existing VoiceSettings dataclass

@dataclass
class ProfileConfig:
    system: SystemSettings = field(default_factory=SystemSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    providers: dict = field(default_factory=lambda: {"cloud": {}, "local": {}})
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    custom_tool_configs: dict = field(default_factory=dict)
    custom_skill_configs: dict = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)
```

### 4.3 Profile Switch Mechanism

```
ProfilesManager.switch_profile("architect"):
  1. Save current state (volatile overrides)
  2. Record switch in event log
  3. Re-load config from hive/profiles/architect/
  4. Load hive/profiles/architect/.env (isolated secrets)
  5. Re-validate
  6. Broadcast profile switch to running loops
```

### 4.4 Secrets Isolation (Per-Profile .env)

Each profile gets its own `.env`:
```
hive/profiles/architect/.env
  OPENROUTER_API_KEY=sk-or-...
  DEEPSEEK_API_KEY=sk-ds-...
```

The `api_key` field in `config.yaml` uses the placeholder pattern `"${OPENROUTER_API_KEY}"` which the loader resolves from the profile's `.env`.

During `switch_profile()`, the old `.env` vars are cleared and the new profile's `.env` is loaded.

---

## 5. Council Agent Profiles Design

Each Evolution Council agent gets a profile optimized for their role:

### Architect
- **Provider**: DeepSeek (heavy reasoning) + local fallback
- **Tools**: Full tool access (write, edit, shell)
- **Memory**: High persistence, full graph mode
- **Safety**: Strict (0.9) — architectural decisions need verification
- **Skills**: architecture-diagram, excalidraw, writing-plans

### Researcher
- **Provider**: Web-capable (Perplexity, Gemini) + local fallback
- **Tools**: Read-only tools, web_fetch, web_search, browser
- **Memory**: Moderate persistence, search-heavy RAG
- **Safety**: Moderate (0.7) — exploration needs less restriction
- **Skills**: arxiv, blogwatcher, youtube-content, web_search

### Planner
- **Provider**: DeepSeek (planning/reasoning) + local
- **Tools**: Planning tools, limited write (plans directory only)
- **Memory**: High persistence, graph mode
- **Safety**: Strict (0.85)
- **Skills**: writing-plans, plan, spike

### Coder
- **Provider**: Coding-optimized (DeepSeek Coder, Claude) + local
- **Tools**: Full write/edit, git, shell (sandboxed workspace)
- **Memory**: Low persistence, code-focus
- **Safety**: Strict (0.9) — code changes need verification
- **Skills**: test-driven-development, systematic-debugging, Hive-driven-development

### Debugger
- **Provider**: Fast inference (Groq, Gemini Flash) + local
- **Tools**: Full write, debug tools, git revert
- **Memory**: Low persistence, session-focus
- **Safety**: Moderate (0.75) — debugging needs speed
- **Skills**: systematic-debugging, debugging-hermes-tui-commands, node-inspect-debugger

### Reviewer
- **Provider**: Best available (GPT-4o, Claude) + local fallback
- **Tools**: Read-only code, git diff, gh pr review
- **Memory**: Low persistence, evidence-focused
- **Safety**: Maximum (0.95) — review must be rigorous
- **Skills**: requesting-code-review, github-code-review

---

## 6. Migration Path

### Phase 1: Create profile system (this task)
- Create `hive/profiles/` directory structure
- Implement `ProfilesManager` (rewrite `core/config_loader.py`)
- Implement schema models
- Create `base` profile from `nexus_config.yaml`
- Create `default` profile (current behavior preserved)
- Deprecate `core/config.py` (redirect to ProfilesManager)

### Phase 2: Council profiles (follow-up task)
- Create 6 council agent profiles
- Wire profile switching into the boot sequence

### Phase 3: Profile-aware boot (follow-up task)
- `nexus.py` reads `NEXUS_PROFILE` env var or `active` in `configs/profiles.yaml`
- CLI flag `--profile architect` overrides
- gui shows active profile

---

## 7. Backward Compatibility

- `NexusConfigLoader` is rewritten as `ProfilesManager` — same API (`get()`, `get_system()`, etc.)
- `configs/nexus_config.yaml` is migrated into `hive/profiles/base/config.yaml` + `hive/profiles/default/config.yaml`
- All existing imports of `NexusConfigLoader` continue to work
- All existing `NEXUS_*` env overrides continue to work (load into active profile)
- Thread-safe singleton pattern preserved

---

## 8. File Creation Plan

| File | Action |
|------|--------|
| `hive/profiles/base/config.yaml` | CREATE — migrated from nexus_config.yaml |
| `hive/profiles/base/.env` | CREATE — template with YOUR_* placeholders |
| `hive/profiles/default/profile.yaml` | CREATE — inherits: base |
| `hive/profiles/default/config.yaml` | CREATE — empty (inherits everything from base) |
| `hive/profiles/default/.env` | CREATE — empty (user supplies secrets) |
| `configs/profiles.yaml` | CREATE — profile registry |
| `core/schema/__init__.py` | CREATE |
| `core/schema/profile.py` | CREATE |
| `core/schema/settings.py` | CREATE |
| `core/config_loader.py` | REWRITE — ProfilesManager |
| `core/config.py` | REWRITE — thin deprecation shim |

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing code that imports config loaders | Keep same module paths, same API signatures |
| Profile switching while tasks are running | Queue switch until current task completes (v1) |
| .env bleed between profiles | Unset old vars before loading new .env |
| Config validation too strict | Warnings-only in v1, upgrade to errors in v2 |
| Filesystem I/O on every get() | Cached in memory, reload on explicit request |

