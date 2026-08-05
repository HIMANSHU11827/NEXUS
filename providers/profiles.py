import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dataclasses_json import DataClassJsonMixin

PROFILES_DIR = Path(os.path.expanduser("~")) / ".nexus" / "auth"
PROFILES_FILE = PROFILES_DIR / "profiles.json"

COOLDOWN_DEFAULTS = {
    "rate_limit": 30,
    "timeout": 60,
    "auth": 600,
    "billing": 18000,
    "server_error": 60,
}

STRATEGY_FILL_FIRST = "fill_first"
STRATEGY_ROUND_ROBIN = "round_robin"
STRATEGY_RANDOM = "random"
SUPPORTED_STRATEGIES = {STRATEGY_FILL_FIRST, STRATEGY_ROUND_ROBIN, STRATEGY_RANDOM}


def _restrict_path(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@dataclass
class ProviderProfile(DataClassJsonMixin):
    name: str
    provider: str
    type: str
    api_key: str = ""
    access: str = ""
    refresh: str = ""
    expires: float = 0.0
    email: Optional[str] = None
    active: bool = True
    cooldown_until: float = 0.0
    cooldown_reason: str = ""
    error_count: int = 0
    last_used: float = 0.0
    usage_count: int = 0
    strategy: str = STRATEGY_FILL_FIRST
    # ``model`` remains the backwards-compatible native identifier. These
    # explicit fields let UI selectors use a friendly alias without losing
    # the provider-native value required for requests.
    model: str = ""
    model_id: str = ""
    model_alias: str = ""
    endpoint: str = ""
    enabled: bool = True

    @property
    def in_cooldown(self) -> bool:
        return self.cooldown_until > time.time()

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - time.time())


class ProviderProfileStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or PROFILES_FILE
        self._profiles: dict[str, list[dict]] = {}
        self._defaults: dict[str, str] = {}
        self._strategies: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = self._path.read_text("utf-8")
                data = json.loads(raw)
                self._profiles = data.get("profiles", {})
                self._defaults = data.get("defaults", {})
                self._strategies = data.get("strategies", {})
            except Exception:
                self._profiles = {}
                self._defaults = {}
                self._strategies = {}
        else:
            self._profiles = {}
            self._defaults = {}
            self._strategies = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_path(self._path.parent, 0o700)
        data = {"profiles": self._profiles, "defaults": self._defaults, "strategies": self._strategies}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), "utf-8")
        _restrict_path(tmp, 0o600)
        tmp.replace(self._path)
        _restrict_path(self._path, 0o600)

    def add_profile(self, profile: ProviderProfile) -> None:
        provider = profile.provider
        if provider not in self._profiles:
            self._profiles[provider] = []
        self._profiles[provider].append(profile.to_dict())
        if len(self._profiles[provider]) == 1:
            self._defaults.setdefault(provider, profile.name)
        self._save()

    def get_profile(self, provider: str, name: Optional[str] = None) -> Optional[ProviderProfile]:
        profiles = self._profiles.get(provider)
        if not profiles:
            return None
        if name:
            for p in profiles:
                if p.get("name") == name and p.get("active", True) and p.get("enabled", True) and not self._in_cooldown(p):
                    return ProviderProfile.from_dict(p)
            return None
        available = self._available_dicts(provider)
        if not available:
            return None
        default_name = self._defaults.get(provider)
        if default_name:
            for p in available:
                if p.get("name") == default_name:
                    return ProviderProfile.from_dict(p)
        return ProviderProfile.from_dict(available[0])

    def list_profiles(self, provider: Optional[str] = None) -> list[ProviderProfile]:
        result = []
        for prov, p_list in self._profiles.items():
            if provider and prov != provider:
                continue
            for p in p_list:
                result.append(ProviderProfile.from_dict(p))
        return result

    def set_default(self, provider: str, name: str) -> bool:
        profiles = self._profiles.get(provider)
        if not profiles:
            return False
        for p in profiles:
            if p.get("name") == name:
                self._defaults[provider] = name
                self._save()
                return True
        return False

    def delete_profile(self, provider: str, name: str) -> bool:
        profiles = self._profiles.get(provider)
        if not profiles:
            return False
        filtered = [p for p in profiles if p.get("name") != name]
        if len(filtered) == len(profiles):
            return False
        self._profiles[provider] = filtered
        if self._defaults.get(provider) == name:
            del self._defaults[provider]
        self._save()
        return True

    def set_strategy(self, provider: str, strategy: str) -> None:
        if strategy in SUPPORTED_STRATEGIES:
            self._strategies[provider] = strategy
            self._save()

    def get_strategy(self, provider: str) -> str:
        return self._strategies.get(provider, STRATEGY_FILL_FIRST)

    def get_api_key(self, provider: str, name: Optional[str] = None) -> Optional[str]:
        profile = self.get_profile(provider, name)
        if profile is None:
            return None
        if profile.type == "api_key":
            return profile.api_key
        if profile.access and profile.expires > time.time() * 1000:
            return profile.access
        return profile.api_key or None

    def next_profile(self, provider: str, current_name: str) -> Optional[ProviderProfile]:
        profiles = self._profiles.get(provider)
        if not profiles:
            return None
        eligible = [p for p in profiles if p.get("active", True) and p.get("enabled", True) and not self._in_cooldown(p)]
        if not eligible:
            return None
        for i, p in enumerate(eligible):
            if p.get("name") == current_name:
                if i + 1 < len(eligible):
                    return ProviderProfile.from_dict(eligible[i + 1])
                return ProviderProfile.from_dict(eligible[0])
        return ProviderProfile.from_dict(eligible[0])

    def mark_inactive(self, provider: str, name: str) -> None:
        profiles = self._profiles.get(provider)
        if not profiles:
            return
        for p in profiles:
            if p.get("name") == name:
                p["active"] = False
                self._save()
                return

    def _available_dicts(self, provider: str) -> list[dict]:
        profiles = self._profiles.get(provider, [])
        return [
            p for p in profiles
            if p.get("active", True) and p.get("enabled", True) and not self._in_cooldown(p)
        ]

    @staticmethod
    def _in_cooldown(profile: dict) -> bool:
        return float(profile.get("cooldown_until", 0.0) or 0.0) > time.time()

    def select(self, provider: str, strategy: Optional[str] = None) -> Optional[ProviderProfile]:
        strategy = strategy or self.get_strategy(provider)
        available = self._available_dicts(provider)
        if not available:
            return None

        if strategy == STRATEGY_RANDOM:
            entry = random.choice(available)
        elif strategy == STRATEGY_ROUND_ROBIN:
            available.sort(key=lambda p: p.get("last_used", 0.0))
            entry = available[0]
        else:
            entry = available[0]

        self._touch(entry)
        return ProviderProfile.from_dict(entry)

    def _touch(self, entry: dict) -> None:
        entry["last_used"] = time.time()
        entry["usage_count"] = entry.get("usage_count", 0) + 1
        self._save()

    def record_failure(self, provider: str, name: str, reason: str = "server_error") -> None:
        profiles = self._profiles.get(provider)
        if not profiles:
            return
        for p in profiles:
            if p.get("name") == name:
                p["error_count"] = p.get("error_count", 0) + 1
                p["cooldown_reason"] = reason
                base = COOLDOWN_DEFAULTS.get(reason, 60)
                backoff = base * min(2 ** (p["error_count"] - 1), 512)
                p["cooldown_until"] = time.time() + backoff
                self._save()
                return

    def record_success(self, provider: str, name: str) -> None:
        profiles = self._profiles.get(provider)
        if not profiles:
            return
        for p in profiles:
            if p.get("name") == name:
                p["error_count"] = 0
                p["cooldown_until"] = 0.0
                p["cooldown_reason"] = ""
                self._save()
                return

    def clear_expired_cooldowns(self) -> int:
        cleared = 0
        now = time.time()
        for profiles in self._profiles.values():
            for p in profiles:
                until = p.get("cooldown_until", 0.0) or 0.0
                if until > 0 and until <= now:
                    p["cooldown_until"] = 0.0
                    p["cooldown_reason"] = ""
                    p["error_count"] = 0
                    cleared += 1
        if cleared:
            self._save()
        return cleared

    def providers(self) -> list[str]:
        return list(self._profiles.keys())

    def count(self, provider: Optional[str] = None) -> int:
        if provider:
            return len(self._profiles.get(provider, []))
        return sum(len(v) for v in self._profiles.values())


_store_instance: Optional[ProviderProfileStore] = None


def load_profile_store() -> ProviderProfileStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = ProviderProfileStore()
    return _store_instance


def resolve_api_key(provider: str, name: Optional[str] = None) -> Optional[str]:
    store = load_profile_store()
    key = store.get_api_key(provider, name)
    if key:
        return key
    env_key = os.environ.get(f"{provider.upper()}_API_KEY") or os.environ.get(f"{provider.upper().replace('-', '_')}_API_KEY")
    return env_key or None
