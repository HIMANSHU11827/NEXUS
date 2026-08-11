import json
import os
import random
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

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

LEASE_MIN_TTL_SECONDS = 1.0
LEASE_MAX_TTL_SECONDS = 3600.0


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


@dataclass(frozen=True)
class ProviderLease:
    """An expiring, process-safe lease for one provider profile.

    The lease token is intentionally opaque and is never derived from the
    credential.  Lease records are persisted separately from profile data so
    older callers can continue to deserialize ``ProviderProfile`` unchanged.
    """

    provider: str
    profile: str
    lease_id: str
    owner_id: str
    expires_at: float

    @property
    def expired(self) -> bool:
        return self.expires_at <= time.time()


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold an advisory lock that works across Nexus processes/platforms."""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_path(lock_path.parent, 0o700)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class ProviderProfileStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else PROFILES_FILE
        self._profiles: dict[str, list[dict]] = {}
        self._defaults: dict[str, str] = {}
        self._strategies: dict[str, str] = {}
        self._leases: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = self._path.read_text("utf-8")
                data = json.loads(raw)
                self._profiles = data.get("profiles", {})
                self._defaults = data.get("defaults", {})
                self._strategies = data.get("strategies", {})
                leases = data.get("leases", {})
                self._leases = leases if isinstance(leases, dict) else {}
            except Exception:
                self._profiles = {}
                self._defaults = {}
                self._strategies = {}
                self._leases = {}
        else:
            self._profiles = {}
            self._defaults = {}
            self._strategies = {}
            self._leases = {}

    def _save(self, *, _lock_held: bool = False) -> None:
        if not _lock_held:
            with _file_lock(self._path):
                # Preserve leases created by another process after this store
                # was loaded.  Profile mutations must not silently revoke a
                # live request's cross-process claim.
                if self._path.exists():
                    try:
                        current = json.loads(self._path.read_text("utf-8"))
                        leases = current.get("leases", {})
                        if isinstance(leases, dict):
                            self._leases = leases
                    except (OSError, ValueError, TypeError):
                        pass
                self._save(_lock_held=True)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_path(self._path.parent, 0o700)
        data = {
            "profiles": self._profiles,
            "defaults": self._defaults,
            "strategies": self._strategies,
            "leases": self._leases,
        }
        # Do not share a fixed ``profiles.tmp`` name between writers.  The
        # advisory lock serializes Nexus writers, but Windows antivirus and
        # indexer activity can still observe/hold a predictable temp path and
        # turn an otherwise atomic replace into WinError 5.  A unique temp in
        # the same directory preserves same-volume atomicity without that
        # collision surface.
        tmp = self._path.with_name(
            f".{self._path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2, default=str))
                handle.flush()
                os.fsync(handle.fileno())
            _restrict_path(tmp, 0o600)
            tmp.replace(self._path)
            _restrict_path(self._path, 0o600)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        with _file_lock(self._path):
            # A lease operation must make its decision from the latest disk
            # state, not from a stale store object in another process.
            self._load()
            yield

    @staticmethod
    def _lease_ttl(ttl_seconds: float) -> float:
        ttl = float(ttl_seconds)
        if not LEASE_MIN_TTL_SECONDS <= ttl <= LEASE_MAX_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be between {LEASE_MIN_TTL_SECONDS:g} and "
                f"{LEASE_MAX_TTL_SECONDS:g}"
            )
        return ttl

    def _lease_entry(self, provider: str, name: str) -> Optional[dict[str, Any]]:
        entry = self._leases.get(provider, {}).get(name)
        if not isinstance(entry, dict):
            return None
        try:
            if float(entry.get("expires_at", 0.0)) <= time.time():
                return None
        except (TypeError, ValueError):
            return None
        return entry

    def _lease_profile_candidates(self, provider: str, name: Optional[str]) -> list[dict]:
        available = self._available_dicts(provider)
        if name:
            return [p for p in available if p.get("name") == name]
        strategy = self.get_strategy(provider)
        if strategy == STRATEGY_RANDOM:
            random.shuffle(available)
        elif strategy == STRATEGY_ROUND_ROBIN:
            available.sort(key=lambda p: p.get("last_used", 0.0))
        return available

    def acquire_lease(
        self,
        provider: str,
        name: Optional[str] = None,
        *,
        ttl_seconds: float = 60.0,
        owner_id: Optional[str] = None,
    ) -> Optional[ProviderLease]:
        """Atomically claim one eligible profile across Nexus processes.

        Leases are exclusive and expire automatically, so a crashed worker
        cannot strand a credential permanently.  The returned lease must be
        passed to :meth:`release_lease` after the request completes.
        """
        ttl = self._lease_ttl(ttl_seconds)
        owner = str(owner_id or f"pid:{os.getpid()}:{uuid.uuid4().hex}")
        now = time.time()
        with self._process_lock():
            candidates = self._lease_profile_candidates(provider, name)
            chosen = next(
                (p for p in candidates if self._lease_entry(provider, str(p.get("name", ""))) is None),
                None,
            )
            if chosen is None:
                return None
            profile_name = str(chosen["name"])
            lease = ProviderLease(
                provider=provider,
                profile=profile_name,
                lease_id=uuid.uuid4().hex,
                owner_id=owner,
                expires_at=now + ttl,
            )
            self._leases.setdefault(provider, {})[profile_name] = {
                "lease_id": lease.lease_id,
                "owner_id": lease.owner_id,
                "expires_at": lease.expires_at,
            }
            chosen["last_used"] = now
            chosen["usage_count"] = int(chosen.get("usage_count", 0) or 0) + 1
            self._save(_lock_held=True)
            return lease

    def renew_lease(self, lease: ProviderLease, *, ttl_seconds: float = 60.0) -> Optional[ProviderLease]:
        """Extend a live lease when its token and owner still match."""
        ttl = self._lease_ttl(ttl_seconds)
        with self._process_lock():
            current = self._lease_entry(lease.provider, lease.profile)
            if not current or current.get("lease_id") != lease.lease_id or current.get("owner_id") != lease.owner_id:
                return None
            renewed = ProviderLease(
                provider=lease.provider,
                profile=lease.profile,
                lease_id=lease.lease_id,
                owner_id=lease.owner_id,
                expires_at=time.time() + ttl,
            )
            current["expires_at"] = renewed.expires_at
            self._save(_lock_held=True)
            return renewed

    def release_lease(self, lease: ProviderLease) -> bool:
        """Release only the exact lease owned by the caller."""
        with self._process_lock():
            current = self._lease_entry(lease.provider, lease.profile)
            if current and current.get("lease_id") == lease.lease_id and current.get("owner_id") == lease.owner_id:
                self._leases.get(lease.provider, {}).pop(lease.profile, None)
                if not self._leases.get(lease.provider):
                    self._leases.pop(lease.provider, None)
                self._save(_lock_held=True)
                return True
            return False

    def add_profile(self, profile: ProviderProfile) -> None:
        with self._process_lock():
            provider = profile.provider
            if provider not in self._profiles:
                self._profiles[provider] = []
            self._profiles[provider].append(profile.to_dict())
            if len(self._profiles[provider]) == 1:
                self._defaults.setdefault(provider, profile.name)
            self._save(_lock_held=True)

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
        with self._process_lock():
            profiles = self._profiles.get(provider)
            if not profiles:
                return False
            for p in profiles:
                if p.get("name") == name:
                    self._defaults[provider] = name
                    self._save(_lock_held=True)
                    return True
            return False

    def delete_profile(self, provider: str, name: str) -> bool:
        with self._process_lock():
            profiles = self._profiles.get(provider)
            if not profiles:
                return False
            filtered = [p for p in profiles if p.get("name") != name]
            if len(filtered) == len(profiles):
                return False
            self._profiles[provider] = filtered
            if self._defaults.get(provider) == name:
                del self._defaults[provider]
            self._save(_lock_held=True)
            return True

    def set_strategy(self, provider: str, strategy: str) -> None:
        if strategy in SUPPORTED_STRATEGIES:
            with self._process_lock():
                self._strategies[provider] = strategy
                self._save(_lock_held=True)

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
