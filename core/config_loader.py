import os
import re
import logging
from typing import Dict, Any, Optional, List
from core.nexus_compat import import_yaml, s  # type: ignore
from utils.singleton import ThreadSafeSingleton

from dotenv import load_dotenv
load_dotenv()

_yaml: Any = import_yaml()
logger = logging.getLogger(__name__)


class NexusConfigLoader(ThreadSafeSingleton):
    """
    NEXUS CONFIG-FIRST LOADER 2.1 — Enhanced with env vars, validation, and thread safety.
    Always resolves config relative to project root, not CWD.
    """

    # Default configuration values
    DEFAULTS = {
        "system.kernel_mode": "recursive_frontier",
        "system.default_provider": "cloud",
        "system.provider_name": "openrouter",
        "system.shell": "ghost_v1",
        "system.branding": "🦀",
        "system.workspace_root": "./workspace",
        "system.log_level": "INFO",
        "security.safety_strictness": 0.8,
        "security.prover_gate_active": True,
        "security.sandbox_mode": "firecracker_ev",
        "memory.vault_mode": "gravity_rag",
        "memory.persistence": "atomic_checkpoints",
    }

    def __init__(self, config_path: Optional[str] = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        if config_path is None:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(_root, "configs", "nexus_config.yaml")
        self.config_path = os.path.abspath(config_path)
        self.data: Dict[str, Any] = self._load()

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _load(self) -> Dict[str, Any]:
        """Load configuration from YAML file with fallback to defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    result = _yaml.safe_load(f)
                    return self._expand_env_refs(result) if isinstance(result, dict) else {}
            except (OSError, _yaml.YAMLError):
                return {}
        return {}

    def _expand_env_refs(self, value: Any) -> Any:
        """Resolve ${ENV_NAME} placeholders without storing secrets in config."""
        if isinstance(value, dict):
            return {k: self._expand_env_refs(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_env_refs(v) for v in value]
        if isinstance(value, str):
            match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
            if match:
                return os.getenv(match.group(1), "")
        return value

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides with NEXUS_ prefix."""
        env_prefix = "NEXUS_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                # Convention: NEXUS_SECTION_SUBSECTION_KEY
                # Example: NEXUS_PROVIDERS_CLOUD_OPENROUTER_API_KEY
                parts = key[len(env_prefix):].lower().split("_")
                
                # Attempt to find the deepest matching section
                curr = self.data
                for i in range(len(parts) - 1):
                    section = "_".join(parts[:i+1])
                    if section in curr:
                        # Found a section, now look for the rest
                        # This handles cases like 'azure_openai' where the section itself has an underscore
                        pass 
                
                # Simplified but smarter approach: Try section by section
                # For now, we'll keep it simple but handle 'api_key' and common underscores
                if len(parts) >= 2:
                    section = parts[0]
                    # Check if it's a known top-level section
                    if section in ["system", "security", "memory", "providers"]:
                        # Join the rest
                        setting = "_".join(parts[1:])
                        # Special case for providers: providers.cloud.name.setting
                        if section == "providers" and len(parts) >= 4:
                            p_type = parts[1] # cloud/local
                            provider_tail = parts[2:]
                            known_settings = (
                                "api_key",
                                "model",
                                "default_model",
                                "model_path",
                                "endpoint",
                                "active",
                                "deployment",
                                "parent_provider",
                            )
                            p_name = "_".join(provider_tail[:-1])
                            p_setting = provider_tail[-1]
                            for setting in sorted(known_settings, key=len, reverse=True):
                                setting_parts = setting.split("_")
                                if provider_tail[-len(setting_parts):] == setting_parts:
                                    p_name = "_".join(provider_tail[:-len(setting_parts)])
                                    p_setting = setting
                                    break
                            if not p_name:
                                continue
                            if p_type not in self.data[section]: self.data[section][p_type] = {}
                            if p_name not in self.data[section][p_type]: self.data[section][p_type][p_name] = {}
                            self.data[section][p_type][p_name][p_setting] = self._convert_type(value)
                        else:
                            if section not in self.data: self.data[section] = {}
                            self.data[section][setting] = self._convert_type(value)

    def _convert_type(self, value: str) -> Any:
        if value.lower() in ("true", "yes", "1"): return True
        if value.lower() in ("false", "no", "0"): return False
        try:
            return int(value) if value.isdigit() else float(value)
        except ValueError:
            return value

    def save(self) -> bool:
        """Persists the current configuration state to disk atomically."""
        temp_path = self.config_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as f:
                _yaml.dump(self.data, f, default_flow_style=False)
            os.replace(temp_path, self.config_path)
            return True
        except Exception as e:
            logger.warning("Failed to save config to %s: %s", self.config_path, e)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.debug("Failed to remove temporary config file %s", temp_path)
            return False

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get nested configuration value using dot notation.
        Falls back to DEFAULTS if not found in config.
        """
        keys = path.split(".")
        curr = self.data
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return self.DEFAULTS.get(path, default)
        return curr

    def get_system(self, key: str, default: Any = None) -> Any:
        return self.get(f"system.{key}", default)

    def get_security(self, key: str, default: Any = None) -> Any:
        return self.get(f"security.{key}", default)

    def get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """Get configuration for a specific provider."""
        cloud_config = self.get(f"providers.cloud.{provider_name}", {})
        if cloud_config:
            return cloud_config

        local_config = self.get(f"providers.local.{provider_name}", {})
        if local_config:
            return local_config

        return {}

    def get_active_providers(self) -> List[str]:
        """Get list of active provider names."""
        active = []

        cloud_providers = self.get("providers.cloud", {})
        if isinstance(cloud_providers, dict):
            for name, config in cloud_providers.items():
                if isinstance(config, dict) and config.get("active", False) and self._provider_has_runtime_access(config, local=False):
                    active.append(name)

        local_providers = self.get("providers.local", {})
        if isinstance(local_providers, dict):
            for name, config in local_providers.items():
                if isinstance(config, dict) and config.get("active", False) and self._provider_has_runtime_access(config, local=True):
                    active.append(name)

        return active

    @staticmethod
    def _provider_has_runtime_access(config: Dict[str, Any], local: bool = False) -> bool:
        """Return whether an active provider can actually be attempted."""
        if local:
            return True
        api_key = str(config.get("api_key", "") or "").strip()
        return bool(api_key and "YOUR_" not in api_key and "${" not in api_key and not api_key.startswith("sk-test"))

    def validate(self) -> List[str]:
        """
        Validate configuration and return list of warnings.
        Empty list means valid configuration.
        """
        warnings = []

        cloud_providers = self.get("providers.cloud", {})
        if isinstance(cloud_providers, dict):
            for name, config in cloud_providers.items():
                if isinstance(config, dict) and config.get("active", False):
                    api_key = config.get("api_key", "")
                    if (
                        not api_key
                        or "YOUR_" in api_key
                        or "${" in api_key
                        or api_key.startswith("sk-test")
                    ):
                        warnings.append(f"Provider '{name}' has placeholder API key")

        log_level = self.get_system("log_level", "INFO")
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if log_level not in valid_levels:
            warnings.append(f"Invalid log level: {log_level}")

        strictness = self.get_security("safety_strictness", 0.8)
        if not (0.0 <= strictness <= 1.0):
            warnings.append(f"Safety strictness out of range: {strictness}")

        return warnings

    def reload(self) -> None:
        """Reload configuration from file."""
        self.data = self._load()
        self._apply_env_overrides()


if __name__ == "__main__":
    loader = NexusConfigLoader()
    print(f"Branding: {loader.get_system('branding')}")
    print(f"Active providers: {loader.get_active_providers()}")
    print(f"Validation warnings: {loader.validate()}")
