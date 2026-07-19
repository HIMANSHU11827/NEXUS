import json
import os
import time
from pathlib import Path
from typing import Optional

from providers.oauth.types import OAuthCredentials

OAUTH_STORE_DIR = Path(os.path.expanduser("~")) / ".nexus" / "auth"
OAUTH_STORE_FILE = OAUTH_STORE_DIR / "oauth_store.json"


def _restrict_path(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


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

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_path(self._path.parent, 0o700)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, default=str), "utf-8")
        _restrict_path(tmp, 0o600)
        tmp.replace(self._path)
        _restrict_path(self._path, 0o600)

    def get(self, provider_id: str) -> Optional[OAuthCredentials]:
        raw = self._data.get(provider_id)
        if raw is None:
            return None
        return OAuthCredentials.from_dict(raw)

    def set(self, provider_id: str, credentials: OAuthCredentials) -> None:
        self._data[provider_id] = credentials.to_dict()
        self._save()

    def delete(self, provider_id: str) -> bool:
        if provider_id in self._data:
            del self._data[provider_id]
            self._save()
            return True
        return False

    def list_providers(self) -> list[str]:
        return list(self._data.keys())

    def clear(self) -> None:
        self._data.clear()
        self._save()


_store_instance: Optional[OAuthTokenStore] = None


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
    from providers.oauth.registry import get_oauth_provider

    store = store or load_oauth_token_store()
    credentials = store.get(provider_id)
    if credentials is None:
        return None

    if time.time() * 1000 >= credentials.expires:
        provider = get_oauth_provider(provider_id)
        if provider is not None:
            try:
                credentials = await provider.refresh_token(credentials)
                store.set(provider_id, credentials)
            except Exception:
                return None

    provider = get_oauth_provider(provider_id)
    if provider is None:
        return credentials.access
    return provider.get_api_key(credentials)
