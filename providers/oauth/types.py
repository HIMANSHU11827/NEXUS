from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from dataclasses_json import DataClassJsonMixin


@dataclass
class OAuthCredentials(DataClassJsonMixin):
    access: str
    refresh: str
    expires: float
    email: Optional[str] = None
    account_id: Optional[str] = None
    enterprise_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthAuthInfo:
    url: str
    instructions: Optional[str] = None


@dataclass
class OAuthPrompt:
    message: str
    placeholder: Optional[str] = None
    allow_empty: bool = False


@dataclass
class OAuthAuthorizationInput:
    code: Optional[str] = None
    state: Optional[str] = None


@dataclass
class OAuthSelectOption:
    id: str
    label: str


@dataclass
class OAuthSelectPrompt:
    message: str
    options: list[OAuthSelectOption]


class OAuthLoginCallbacks(Protocol):
    def on_auth(self, info: OAuthAuthInfo) -> None: ...

    async def on_prompt(self, prompt: OAuthPrompt) -> str: ...

    def on_progress(self, message: str) -> None: ...

    async def on_manual_code_input(self) -> Optional[str]: ...

    async def on_select(self, prompt: OAuthSelectPrompt) -> Optional[str]: ...

    @property
    def signal(self) -> Optional[Any]: ...


class OAuthProviderInterface(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredentials: ...

    async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials: ...

    def get_api_key(self, credentials: OAuthCredentials) -> str: ...
