import json
import os
import time
import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from models.providers.auth.oauth.expiry import OAUTH_REFRESH_SKEW_MS
from models.providers.auth.oauth.types import OAuthCredentials

OAUTH_STORE_DIR = Path(os.path.expanduser("~")) / ".nexus" / "auth"
OAUTH_STORE_FILE = OAUTH_STORE_DIR / "oauth_store.json"


def _restrict_path(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Serialize OAuth store mutations across Nexus processes."""
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


class OAuthTokenStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or OAUTH_STORE_FILE
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = self._path.read_text("utf-8")
                self._data = json.loads(raw)
            except Exception:
                self._data = {}
        else:
            self._data = {}

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        with _file_lock(self._path):
            self._load()
            yield

    def _save(self, *, _lock_held: bool = False) -> None:
        if not _lock_held:
            with self._process_lock():
                self._save(_lock_held=True)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_path(self._path.parent, 0o700)
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._data, indent=2, default=str))
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

    def get(self, provider_id: str) -> Optional[OAuthCredentials]:
        with self._process_lock():
            raw = self._data.get(provider_id)
            if raw is None:
                return None
            return OAuthCredentials.from_dict(raw)

    def set(self, provider_id: str, credentials: OAuthCredentials) -> None:
        with self._process_lock():
            self._data[provider_id] = credentials.to_dict()
            self._save(_lock_held=True)

    def delete(self, provider_id: str) -> bool:
        with self._process_lock():
            if provider_id in self._data:
                del self._data[provider_id]
                self._save(_lock_held=True)
                return True
            return False

    def list_providers(self) -> list[str]:
        with self._process_lock():
            return list(self._data.keys())

    def clear(self) -> None:
        with self._process_lock():
            self._data.clear()
            self._save(_lock_held=True)


_store_instance: Optional[OAuthTokenStore] = None
_refresh_lock_guard = threading.Lock()
_refresh_locks: dict[tuple[str, int], asyncio.Lock] = {}


def _refresh_lock(provider_id: str) -> asyncio.Lock:
    """Return a single-flight lock scoped to provider and running loop."""
    key = (str(provider_id), id(asyncio.get_running_loop()))
    with _refresh_lock_guard:
        lock = _refresh_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _refresh_locks[key] = lock
        return lock


def load_oauth_token_store() -> OAuthTokenStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = OAuthTokenStore()
    return _store_instance


def save_oauth_token_store() -> None:
    if _store_instance is not None:
        _store_instance._save()


async def get_oauth_api_key(
    provider_id: str,
    store: Optional[OAuthTokenStore] = None,
) -> Optional[str]:
    from models.providers.auth.oauth.registry import get_oauth_provider

    store = store or load_oauth_token_store()
    credentials = store.get(provider_id)
    if credentials is None:
        return None

    if time.time() * 1000 + OAUTH_REFRESH_SKEW_MS >= credentials.expires:
        provider = get_oauth_provider(provider_id)
        if provider is not None:
            try:
                async with _refresh_lock(provider_id):
                    # Another waiter may have completed the refresh while it
                    # was queued. Re-read and avoid issuing a second token.
                    current = store.get(provider_id)
                    if current is not None and time.time() * 1000 + OAUTH_REFRESH_SKEW_MS < current.expires:
                        credentials = current
                    else:
                        credentials = await provider.refresh_token(current or credentials)
                        store.set(provider_id, credentials)
            except Exception:
                return None

    provider = get_oauth_provider(provider_id)
    if provider is None:
        return credentials.access
    return provider.get_api_key(credentials)
