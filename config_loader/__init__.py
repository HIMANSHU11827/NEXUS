"""
NEXUS Profiles Manager — Unified, profile-aware configuration system.

Replaces BOTH NexusConfig (core/config.py) and NexusConfigLoader (this module).

Design:
  - Named profiles with inheritance (base → default → profile)
  - Per-profile isolated .env loading (secrets never mix)
  - Deep-merge config resolution (inheritance chain)
  - Pydantic validation via core/schema/
  - Runtime profile switching
  - Thread-safe singleton

Usage:
    from config_loader import ProfilesManager

    # Get the singleton
    pm = ProfilesManager()

    # Access config (dot notation — same API as existing loaders)
    branding = pm.get("system.branding")

    # Profile management
    pm.switch_profile("researcher")
    profiles = pm.list_profiles()
    info = pm.get_profile("architect")
    warnings = pm.validate_profile("default")

    # Backward-compatible shortcuts
    pm.get_system("log_level")
    pm.get_security("safety_strictness")
    pm.get_active_providers()
"""

from __future__ import annotations

import os
import re
import copy
import logging
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from nexus_compat import import_yaml, s  # type: ignore

logger = logging.getLogger(__name__)

# Try importing schema models; fall back to dict-based if not available
try:
    from schema.settings import ProfileConfig, SystemSettings, SecuritySettings, MemorySettings, VoiceSettings
    from schema.profile import ProfileMeta, ProfileRegistry
    HAS_SCHEMA = True
except ImportError:
    HAS_SCHEMA = False
    logger.debug("Schema models not available; using dict-based config")

# Simple thread-safe singleton implementation (no external deps)
# Matches the pattern used by the existing NexusConfigLoader


class SingletonMeta(type):
    _instances: Dict = {}
    _lock: Any = None

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            import threading
            if cls._lock is None:
                cls._lock = threading.RLock()
            with cls._lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]


class ProfilesManager(metaclass=SingletonMeta):
    """
    Single entry point for all NEXUS configuration.

    Features:
    - Named profile management with base→profile inheritance
    - Per-profile isolated .env loading
    - Deep-merge config from inheritance chain
    - Runtime profile switching
    - Backward-compatible with NexusConfigLoader API
    """
    _instance = None

    @classmethod
    def _reset_instance(cls):
        """Reset the singleton instance (for testing)."""
        cls._instances.pop(cls, None)
        cls._instance = None

    # Root directory cache (lazy)
    _nexus_root: Optional[str] = None

    def __init__(self, nexus_root: Optional[str] = None) -> None:
        """Initialize the ProfilesManager.

        Args:
            nexus_root: Absolute path to NEXUS project root.
                        If None, auto-detected from file location.
        """
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # Determine NEXUS root
        if nexus_root:
            self._nexus_root = os.path.abspath(nexus_root)
        else:
            self._nexus_root = self._detect_root()

        # Config data
        self._yaml: Any = import_yaml()

        # In-memory cache
        self._registry: Optional[dict] = None
        self._active_profile_name: str = "default"
        self._active_config: Optional[dict] = None
        self._active_config_typed: Optional[Any] = None
        self._profile_cache: Dict[str, dict] = {}

        # Track loaded env vars for cleanup during switching
        self._loaded_env_keys: set = set()

        # Bootstrap — load registry and active profile
        self._load_registry()
        self._load_active_profile()

        logger.info("[PROFILES] Active profile: %s", self._active_profile_name)

    # ---- Public API ----

    @property
    def active_profile(self) -> str:
        """Name of the currently active profile."""
        return self._active_profile_name

    @property
    def data(self) -> dict:
        """Resolved active configuration for legacy callers.

        Older gui and tool code reads and mutates ``config.data`` directly.
        Keep that contract pointed at the active profile config while the profile
        manager remains the source of truth.
        """
        if self._active_config is None:
            self._active_config = {}
        return self._active_config

    @data.setter
    def data(self, value: dict) -> None:
        self._active_config = value if isinstance(value, dict) else {}
        self._active_config_typed = None

    def get(self, path: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation.

        Args:
            path: Dot-separated path, e.g. 'system.branding'
            default: Value to return if path not found

        Returns:
            Configuration value, or default
        """
        if not self._active_config:
            return default
        keys = path.split(".")
        curr = self._active_config
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return default
        return curr

    def get_system(self, key: str, default: Any = None) -> Any:
        """Shortcut for get('system.<key>', default)."""
        return self.get(f"system.{key}", default)

    def get_security(self, key: str, default: Any = None) -> Any:
        """Shortcut for get('security.<key>', default)."""
        return self.get(f"security.{key}", default)

    def get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """Get configuration for a specific provider in the active profile."""
        provider_key = str(provider_name or "").strip()
        providers = self.get("providers", {})
        if not isinstance(providers, dict):
            return {}
        for section_name in ("cloud", "local"):
            section = providers.get(section_name, {})
            if not isinstance(section, dict):
                continue
            direct = section.get(provider_key)
            if direct:
                return direct
            lowered = provider_key.lower()
            for name, config in section.items():
                if str(name).lower() == lowered and isinstance(config, dict):
                    return config
        return {}

    def get_active_providers(self) -> List[str]:
        """Get list of active provider names for the current profile."""
        active = []
        cloud_providers = self.get("providers.cloud", {})
        if isinstance(cloud_providers, dict):
            for name, config in cloud_providers.items():
                if isinstance(config, dict) and config.get("active", False):
                    if self._provider_has_runtime_access(config, local=False):
                        active.append(name)
        local_providers = self.get("providers.local", {})
        if isinstance(local_providers, dict):
            for name, config in local_providers.items():
                if isinstance(config, dict) and config.get("active", False):
                    if self._provider_has_runtime_access(config, local=True):
                        active.append(name)
        return active

    def list_profiles(self) -> List[str]:
        """List all known profile names."""
        if not self._registry:
            return ["default", "base"]
        profiles_dict = self._registry.get("profiles", {})
        return list(profiles_dict.keys())

    def get_profile(self, name: str) -> Optional[dict]:
        """Get metadata for a named profile.

        Returns dict with keys: name, path, inherits, description, tags
        """
        if not self._registry:
            return None
        profiles_dict = self._registry.get("profiles", {})
        info = profiles_dict.get(name)
        if info:
            return {"name": name, **info}
        return None

    def switch_profile(self, name: str) -> bool:
        """Switch the active profile at runtime.

        Args:
            name: Profile name to switch to

        Returns:
            True if successful, False if profile doesn't exist
        """
        if name == self._active_profile_name:
            return True

        if not self._profile_exists(name):
            logger.warning("[PROFILES] Cannot switch — profile '%s' not found", name)
            return False

        # Unload current profile's env vars
        self._unload_env()

        # Load new profile
        self._active_profile_name = name
        self._load_active_profile()

        # Update registry
        if self._registry:
            self._registry["active"] = name
            self._save_registry()

        logger.info("[PROFILES] Switched to profile: %s", name)
        return True

    def validate_profile(self, name: str) -> List[str]:
        """Validate a profile's resolved configuration.

        Returns a list of warning strings (empty = valid).
        """
        if not self._profile_exists(name):
            return [f"Profile '{name}' not found"]

        # Load and resolve the profile's config
        config = self._resolve_profile_config(name)
        if not config:
            return [f"Failed to load config for profile '{name}'"]

        warnings = []

        # Validate log level
        log_level = self._dict_get(config, "system.log_level", "INFO")
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if log_level not in valid_levels:
            warnings.append(f"Invalid log level: {log_level}")

        # Validate safety strictness
        strictness = self._dict_get(config, "security.safety_strictness", 0.8)
        if not (0.0 <= strictness <= 1.0):
            warnings.append(f"Safety strictness out of range: {strictness}")

        # Check for placeholder API keys
        cloud_providers = config.get("providers", {}).get("cloud", {})
        if isinstance(cloud_providers, dict):
            for pname, pconfig in cloud_providers.items():
                if isinstance(pconfig, dict) and pconfig.get("active", False):
                    api_key = pconfig.get("api_key", "")
                    if not api_key or "YOUR_" in api_key:
                        warnings.append(f"Provider '{pname}' has placeholder or empty API key")

        return warnings

    def reload(self) -> None:
        """Reload all configuration from disk."""
        self._profile_cache.clear()
        self._load_registry()
        self._load_active_profile()
        logger.info("[PROFILES] Configuration reloaded")

    def save(self) -> bool:
        """Persist the current active configuration to disk.

        Saves to the active profile's config.yaml file.
        """
        if not self._active_config:
            return False
        profile_path = self._get_profile_path(self._active_profile_name)
        if not profile_path:
            return False
        config_path = os.path.join(profile_path, "config.yaml")
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                self._yaml.dump(self._active_config, f, default_flow_style=False)
            return True
        except Exception as e:
            logger.warning("[PROFILES] Failed to save config: %s", e)
            return False

    # ---- Internal Methods ----

    def _detect_root(self) -> str:
        """Auto-detect NEXUS project root."""
        # Walk up from this file's location
        this_file = os.path.abspath(__file__)
        current = os.path.dirname(os.path.dirname(this_file))
        if os.path.exists(os.path.join(current, "pyproject.toml")):
            return current
        # Try cwd
        cwd = os.getcwd()
        if os.path.exists(os.path.join(cwd, "pyproject.toml")):
            return cwd
        # Fallback
        return current

    def _nexus_root(self) -> str:
        """Get or compute NEXUS project root."""
        if self._nexus_root is not None:
            return self._nexus_root
        self._nexus_root = self._detect_root()
        return self._nexus_root

    def _load_registry(self) -> None:
        """Load the profile registry from configs/profiles.yaml."""
        registry_path = os.path.join(self._nexus_root, "configs", "profiles.yaml")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = self._yaml.safe_load(f)
                if isinstance(data, dict):
                    self._registry = data
                    self._active_profile_name = data.get("active", "default")
            except Exception as e:
                logger.warning("[PROFILES] Failed to load registry: %s", e)
                self._registry = {"active": "default", "profiles": {"base": {"path": "hive/profiles/base"}, "default": {"path": "hive/profiles/default"}}}
        else:
            # No registry yet — create defaults
            self._registry = {"active": "default", "profiles": {"base": {"path": "hive/profiles/base"}, "default": {"path": "hive/profiles/default"}}}

    def _save_registry(self) -> bool:
        """Persist the profile registry."""
        registry_path = os.path.join(self._nexus_root, "configs", "profiles.yaml")
        try:
            os.makedirs(os.path.dirname(registry_path), exist_ok=True)
            with open(registry_path, "w", encoding="utf-8") as f:
                self._yaml.dump(self._registry, f, default_flow_style=False)
            return True
        except Exception as e:
            logger.warning("[PROFILES] Failed to save registry: %s", e)
            return False

    def _profile_exists(self, name: str) -> bool:
        """Check if a profile exists on disk."""
        if name == "base":
            return any(
                os.path.isdir(os.path.join(self._nexus_root, root, "base"))
                for root in ("hive/profiles", "profiles")
            )
        profile_path = self._get_profile_path(name)
        return profile_path is not None and os.path.isdir(profile_path)

    def _get_profile_path(self, name: str) -> Optional[str]:
        """Get the filesystem path for a profile directory."""
        # Check registry first
        if self._registry:
            profiles_dict = self._registry.get("profiles", {})
            info = profiles_dict.get(name)
            if info:
                path = info.get("path", "")
                if path:
                    full_path = os.path.join(self._nexus_root, path)
                    if os.path.isdir(full_path):
                        return full_path
        # Fallback: check canonical hive/profiles/<name>, then legacy profiles/<name>.
        for root in ("hive/profiles", "profiles"):
            direct = os.path.join(self._nexus_root, root, name)
            if os.path.isdir(direct):
                return direct
        return None

    def _load_profile_yaml(self, profile_path: str, filename: str) -> dict:
        """Load a YAML file from a profile directory."""
        filepath = os.path.join(profile_path, filename)
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = self._yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("[PROFILES] Failed to load %s/%s: %s", profile_path, filename, e)
            return {}

    def _resolve_inheritance_chain(self, profile_name: str) -> List[str]:
        """Resolve the inheritance chain for a profile (base first, profile last)."""
        chain = []
        visited = set()

        def resolve(name: str):
            if name in visited:
                logger.warning("[PROFILES] Circular inheritance detected for '%s'", name)
                return
            if not name:
                return
            visited.add(name)

            # Load profile.yaml to find inherits
            profile_path = self._get_profile_path(name)
            if not profile_path:
                return

            meta = self._load_profile_yaml(profile_path, "profile.yaml")
            parent = meta.get("inherits", "")
            if parent:
                resolve(parent)

            chain.append(name)

        resolve(profile_name)
        return chain

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge override into base. Lists are replaced, not merged."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def _resolve_profile_config(self, profile_name: str) -> Optional[dict]:
        """Resolve a profile's full config by walking its inheritance chain.

        Caches resolved configs per profile.
        """
        if profile_name in self._profile_cache:
            return copy.deepcopy(self._profile_cache[profile_name])

        # Get inheritance chain (base first, profile last)
        chain = self._resolve_inheritance_chain(profile_name)
        if not chain:
            logger.warning("[PROFILES] Could not resolve inheritance chain for '%s'", profile_name)
            return None

        # Load configs in order and merge
        resolved: dict = {}
        for name in chain:
            profile_path = self._get_profile_path(name)
            if not profile_path:
                logger.debug("[PROFILES] No profile path for '%s', skipping", name)
                continue
            config = self._load_profile_yaml(profile_path, "config.yaml")
            resolved = self._deep_merge(resolved, config)

        # Cache and return
        self._profile_cache[profile_name] = copy.deepcopy(resolved)
        return resolved

    def _load_env_file(self, env_path: str) -> None:
        """Load a dotenv-style file without overwriting real environment values."""
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Skip placeholders
                        if "YOUR_" in value or not value:
                            continue
                        # Resolve ${VAR} references
                        resolved = self._resolve_env_var(value)
                        # Only set if not already set by environment
                        if key not in os.environ:
                            os.environ[key] = resolved
                            self._loaded_env_keys.add(key)
            except Exception as e:
                logger.warning("[PROFILES] Failed to load env file '%s': %s", env_path, e)

    def _load_env_for_profile(self, profile_name: str) -> None:
        """Load root and profile .env files, expanding ${VAR} references.

        Also loads NEXUS_* env vars as overrides.
        """
        # The root .env is the common local setup path used by the gui and
        # CLI. Profile-specific .env files can still override by setting real
        # process env vars before launch.
        if self._nexus_root:
            self._load_env_file(os.path.join(self._nexus_root, ".env"))

        profile_path = self._get_profile_path(profile_name)
        if profile_path:
            self._load_env_file(os.path.join(profile_path, ".env"))

        # Apply NEXUS_* env overrides to config data
        self._apply_env_overrides()

    def _resolve_env_var(self, value: str) -> str:
        """Resolve ${VAR} references in a string value."""
        match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
        if match:
            return os.environ.get(match.group(1), "")
        return value

    def _unload_env(self) -> None:
        """Unload environment variables that were set by the previous profile."""
        for key in list(self._loaded_env_keys):
            os.environ.pop(key, None)
        self._loaded_env_keys.clear()

    def _apply_env_overrides(self) -> None:
        """Apply NEXUS_* environment variable overrides into active config."""
        if not self._active_config:
            return

        env_prefix = "NEXUS_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                parts = key[len(env_prefix):].lower().split("_")
                if len(parts) >= 2:
                    section = parts[0]
                    if section in ("system", "security", "memory", "providers"):
                        setting = "_".join(parts[1:])
                        if section not in self._active_config:
                            self._active_config[section] = {}
                        # Convert type
                        self._active_config[section][setting] = self._convert_type(value)

    def _convert_type(self, value: str) -> Any:
        """Convert string values to appropriate types."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value) if value.isdigit() else float(value)
        except ValueError:
            return value

    def _expand_env_placeholders(self, obj: Any) -> Any:
        """Recursively expand ${VAR_NAME} placeholders from the process environment."""
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if isinstance(value, str):
                    obj[key] = re.sub(
                        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                        lambda match: os.environ.get(match.group(1), match.group(0)),
                        value,
                    )
                else:
                    self._expand_env_placeholders(value)
            return obj
        if isinstance(obj, list):
            for item in obj:
                self._expand_env_placeholders(item)
            return obj
        return obj

    def _load_active_profile(self) -> None:
        """Load the active profile's fully resolved configuration."""
        # Load .env before resolving ${VAR} placeholders in YAML provider keys.
        self._load_env_for_profile(self._active_profile_name)

        self._active_config = self._resolve_profile_config(self._active_profile_name)
        if self._active_config is None:
            logger.error("[PROFILES] Failed to load active profile '%s'", self._active_profile_name)
            self._active_config = {}
        else:
            self._expand_env_placeholders(self._active_config)

        # Apply NEXUS_* env overrides
        self._apply_env_overrides()

        # Build typed config if schema is available
        if HAS_SCHEMA:
            try:
                self._active_config_typed = ProfileConfig(
                    system=SystemSettings.from_dict(self._active_config.get("system")),
                    security=SecuritySettings.from_dict(self._active_config.get("security")),
                    memory=MemorySettings.from_dict(self._active_config.get("memory")),
                    voice=VoiceSettings.from_dict(self._active_config.get("voice")),
                    providers=self._active_config.get("providers", {}),
                    custom_tool_configs=self._active_config.get("custom_tool_configs", {}),
                    custom_skill_configs=self._active_config.get("custom_skill_configs", {}),
                    mcp_servers=self._active_config.get("mcp_servers", {}),
                    disabled_skills=self._active_config.get("disabled_skills", []),
                    disabled_tools=self._active_config.get("disabled_tools", []),
                )
            except Exception as e:
                logger.warning("[PROFILES] Failed to build typed config: %s", e)
                self._active_config_typed = None

    @staticmethod
    def _dict_get(data: dict, path: str, default: Any = None) -> Any:
        """Get value from nested dict using dot notation."""
        keys = path.split(".")
        curr = data
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return default
        return curr

    @staticmethod
    def _provider_has_runtime_access(config: dict, local: bool = False) -> bool:
        """Return whether an active provider can actually be attempted."""
        endpoint = str(config.get("endpoint", "") or "").strip()
        if endpoint == "local-cli":
            return True
        if local:
            parent = str(config.get("parent_provider", "") or "").strip()
            if parent:
                key = os.environ.get(f"{parent.upper()}_API_KEY", "").strip()
                return bool(key and "YOUR_" not in key and "$" not in key)
            endpoint = str(config.get("endpoint", "") or "").strip()
            parsed = urlparse(endpoint)
            if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
                try:
                    with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.25):
                        return True
                except OSError:
                    return False
            return True
        api_key = str(config.get("api_key", "") or "").strip()
        if not api_key:
            # Let normal local development keep secrets in .env instead of YAML.
            parent = str(config.get("parent_provider", "") or "").strip()
            env_name = f"{parent or ''}".upper() if parent else ""
            api_key = os.environ.get(f"{env_name}_API_KEY", "") if env_name else ""
        return bool(api_key and "YOUR_" not in api_key and "$" not in api_key)


# ---- Backward Compatibility Aliases ----
# These ensure existing code that imports NexusConfigLoader continues to work.

class NexusConfigLoader(ProfilesManager):
    """
    Backward-compatible alias for ProfilesManager.
    
    Supports both:
    - Directory mode: NexusConfigLoader('/path/to/nexus') -> use ProfilesManager
    - File mode: NexusConfigLoader('/path/to/config.yaml') -> load single file

    Deprecated: Use ProfilesManager directly.
    """
    
    def __init__(self, path_or_root: Optional[str] = None) -> None:
        """Initialize loader, handling both file and directory paths."""
        # If a file path is passed (for tests), load it directly
        # Check if it's a file path: either exists as a file, or ends with .yaml/.yml
        is_file_path = path_or_root and (os.path.isfile(path_or_root) or 
                                          path_or_root.endswith(('.yaml', '.yml')))
        
        if is_file_path:
            self._file_mode = True
            self._config_file_path = os.path.abspath(path_or_root)
            self._yaml = import_yaml()
            self._active_config = self._load_config_file(self._config_file_path)
            self._active_config_typed = None
            self._active_profile_name = "default"
            self._loaded_env_keys = set()
            self._initialized = True
            # Apply env expansions and overrides in file mode
            self._expand_env_placeholders(self._active_config)
            self._apply_env_overrides()
            return
        
        # Otherwise, use ProfilesManager (directory mode)
        self._file_mode = False
        self._config_file_path = None
        super().__init__(path_or_root)
    
    def _load_config_file(self, filepath: str) -> dict:
        """Load a single YAML config file."""
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = self._yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("[CONFIG] Failed to load %s: %s", filepath, e)
            return {}
    
    def _expand_env_placeholders(self, obj: Any) -> Any:
        """Recursively expand ${VAR_NAME} placeholders with environment variables."""
        import re
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    # Replace ${VAR} with env var value
                    def replace_var(match):
                        var_name = match.group(1)
                        return os.environ.get(var_name, match.group(0))
                    obj[key] = re.sub(r'\$\{([^}]+)\}', replace_var, value)
                else:
                    self._expand_env_placeholders(value)
            return obj
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._expand_env_placeholders(item)
            return obj
        return obj
    
    def _apply_env_overrides(self) -> None:
        """Apply NEXUS_* environment variable overrides to configuration."""
        prefix = "NEXUS_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # NEXUS_PROVIDERS_CLOUD_OPENROUTER_API_KEY -> providers.cloud.openrouter.api_key
                # Smart splitting that preserves compound keys like api_key
                path_str = key[len(prefix):].lower()
                path_parts = self._smart_split_path(path_str)
                self._set_nested_value_from_path(self._active_config, path_parts, value)
    
    def _smart_split_path(self, path_str: str) -> List[str]:
        """Split a path string intelligently, preserving compound keys like api_key."""
        # Known compound keys that should stay together
        compounds = ['api_key', 'model_name', 'api_base', 'org_id']
        
        result = []
        remaining = path_str
        while remaining:
            # Try to match a compound key first
            matched = False
            for compound in compounds:
                if remaining.lower().startswith(compound):
                    result.append(compound)
                    remaining = remaining[len(compound):]
                    if remaining.startswith('_'):
                        remaining = remaining[1:]
                    matched = True
                    break
            
            if not matched:
                # Find next underscore
                idx = remaining.find('_')
                if idx == -1:
                    if remaining:
                        result.append(remaining)
                    break
                else:
                    result.append(remaining[:idx])
                    remaining = remaining[idx+1:]
        
        return result


    
    
    def _set_nested_value_from_path(self, obj: dict, path_parts: List[str], value: Any) -> None:
        """Set a value in a nested dict using a path list of keys."""
        if not path_parts or not isinstance(obj, dict):
            return
        
        current = obj
        # Navigate/create nested dicts up to the second-to-last key
        for part in path_parts[:-1]:
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                # If it's not a dict, we can't continue
                return
            current = current[part]
        # Set the final value
        current[path_parts[-1]] = value
    
    def save(self) -> bool:
        """Persist configuration (file mode only)."""
        if self._file_mode:
            if not self._active_config or not self._config_file_path:
                return False
            try:
                os.makedirs(os.path.dirname(self._config_file_path), exist_ok=True)
                with open(self._config_file_path, "w", encoding="utf-8") as f:
                    self._yaml.dump(self._active_config, f, default_flow_style=False)
                return True
            except Exception as e:
                logger.warning("[CONFIG] Failed to save: %s", e)
                return False
        # Directory mode: use parent implementation
        return super().save()
    
    def reload(self) -> None:
        """Reload configuration."""
        if self._file_mode and self._config_file_path:
            self._active_config = self._load_config_file(self._config_file_path)
            self._expand_env_placeholders(self._active_config)
            self._apply_env_overrides()
        else:
            super().reload()
    
    def validate(self) -> List[str]:
        """Validate configuration (backward compatibility for tests)."""
        if self._file_mode:
            # Simple file mode validation
            warnings = []
            if not self._active_config:
                warnings.append("Configuration is empty")
            return warnings
        # Directory mode: use parent implementation via validate_profile
        return self.validate_profile(self._active_profile_name)


# Singleton instance for quick import
_config_manager: Optional[ProfilesManager] = None


def get_config() -> ProfilesManager:
    """Get the global ProfilesManager singleton.

    This replaces both get_config() from core/config.py and
    direct NexusConfigLoader() instantiation.
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = ProfilesManager()
    return _config_manager


# ---- Entry point for testing ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    pm = ProfilesManager()
    print(f"Active profile: {pm.active_profile}")
    print(f"Branding: {pm.get('system.branding')}")
    print(f"Default provider: {pm.get('system.default_provider')}")
    print(f"Provider name: {pm.get('system.provider_name')}")
    print(f"Active providers: {pm.get_active_providers()}")
    print(f"All profiles: {pm.list_profiles()}")
    warnings = pm.validate_profile(pm.active_profile)
    if warnings:
        print(f"Warnings: {warnings}")
    else:
        print("Config validation: OK")
