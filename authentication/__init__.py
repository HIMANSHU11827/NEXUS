"""Authentication module for NEXUS AI dashboard & API.

Supports:
- Token-based auth (``NEXUS_DASHBOARD_TOKEN`` env var)
- OAuth 2.0 providers: Google, GitHub
- Signed session cookies via Starlette SessionMiddleware
- FastAPI middleware + dependency injection
- Gateway authorization helpers
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

logger = logging.getLogger("nexus.auth")

# ── Env-based token ──────────────────────────────────────────────────
_AUTH_TOKEN = os.environ.get("NEXUS_DASHBOARD_TOKEN", "").strip()
_OAUTH_STATE_SECRET = os.environ.get("NEXUS_OAUTH_SECRET", "").strip() or secrets.token_hex(32)
_SESSION_SECRET = os.environ.get("NEXUS_SESSION_SECRET", "").strip() or secrets.token_hex(32)

# ── OAuth provider configs ──────────────────────────────────────────

OAUTH_PROVIDERS: Dict[str, Dict[str, str]] = {}

_google_id = os.environ.get("NEXUS_GOOGLE_CLIENT_ID", "").strip()
_google_secret = os.environ.get("NEXUS_GOOGLE_CLIENT_SECRET", "").strip()
if _google_id and _google_secret:
    OAUTH_PROVIDERS["google"] = {
        "client_id": _google_id,
        "client_secret": _google_secret,
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scope": "openid email profile",
    }

_github_id = os.environ.get("NEXUS_GITHUB_CLIENT_ID", "").strip()
_github_secret = os.environ.get("NEXUS_GITHUB_CLIENT_SECRET", "").strip()
if _github_id and _github_secret:
    OAUTH_PROVIDERS["github"] = {
        "client_id": _github_id,
        "client_secret": _github_secret,
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    }


# ── Dataclasses ─────────────────────────────────────────────────────

@dataclass
class AuthUser:
    provider: str
    sub: str
    name: str = ""
    email: str = ""
    avatar_url: str = ""
    authenticated_at: float = field(default_factory=time.time)

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.sub}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "sub": self.sub,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "authenticated_at": self.authenticated_at,
        }


@dataclass
class AuthResult:
    success: bool
    user: Optional[AuthUser] = None
    error: str = ""


# ── Token validation ────────────────────────────────────────────────

def _constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def validate_dashboard_token(token: str) -> bool:
    """Validate the supplied token against the saved NEXUS_DASHBOARD_TOKEN."""
    if not _AUTH_TOKEN:
        return False
    if not token:
        return False
    return _constant_time_compare(token, _AUTH_TOKEN)


# ── OAuth helpers ───────────────────────────────────────────────────

def _generate_state(provider: str) -> str:
    raw = f"{provider}:{time.time()}:{secrets.token_hex(16)}"
    sig = hmac.new(
        _OAUTH_STATE_SECRET.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    state = f"{sig}:{raw}"
    return state


def _verify_state(state: str, provider: str, max_age: int = 600) -> bool:
    try:
        sig_part, *rest = state.split(":", 1)
        if not rest:
            return False
        raw = rest[0]
        provider_part, ts_str, _ = raw.split(":", 2)
        if provider_part != provider:
            return False
        ts = float(ts_str)
        if time.time() - ts > max_age:
            return False
        expected_sig = hmac.new(
            _OAUTH_STATE_SECRET.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]
        return _constant_time_compare(sig_part, expected_sig)
    except (ValueError, IndexError):
        return False


def get_oauth_authorize_url(provider: str, redirect_uri: str) -> Tuple[str, str]:
    """Get the OAuth authorize URL and state.

    Returns:
        Tuple of (authorize_url, state). The state must be passed to
        ``handle_oauth_callback`` for verification.
    """
    config = OAUTH_PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unknown OAuth provider: {provider}")

    state = _generate_state(provider)
    params = urlencode(
        {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": config["scope"],
            "state": state,
            "response_type": "code",
            "access_type": "offline",
        }
    )
    url = f"{config['authorize_url']}?{params}"
    return url, state


async def handle_oauth_callback(
    provider: str,
    code: str,
    state: str,
    redirect_uri: str,
) -> AuthResult:
    """Handle the OAuth callback — exchange code for tokens and fetch user info."""
    config = OAUTH_PROVIDERS.get(provider)
    if not config:
        return AuthResult(success=False, error=f"Unknown provider: {provider}")

    if not _verify_state(state, provider):
        return AuthResult(success=False, error="Invalid or expired state")

    import httpx

    # Exchange code for access token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            if provider == "github":
                token_data["accept"] = "json"
                headers = {"Accept": "application/json"}
            else:
                headers = {}

            token_resp = await client.post(config["token_url"], data=token_data, headers=headers)
            if token_resp.status_code != 200:
                return AuthResult(
                    success=False,
                    error=f"Token exchange failed: HTTP {token_resp.status_code}",
                )

            token_json = token_resp.json()
            access_token = token_json.get("access_token", "")

            if not access_token:
                return AuthResult(success=False, error="No access_token in response")

            # Fetch user info
            user_headers = {"Authorization": f"Bearer {access_token}"}
            if provider == "github":
                user_headers["Accept"] = "application/vnd.github.v3+json"
                user_headers["User-Agent"] = "NEXUS-AI"

            user_resp = await client.get(config["userinfo_url"], headers=user_headers)
            if user_resp.status_code != 200:
                return AuthResult(
                    success=False,
                    error=f"Userinfo fetch failed: HTTP {user_resp.status_code}",
                )

            user_data = user_resp.json()
            user = _parse_userinfo(provider, user_data)
            return AuthResult(success=True, user=user)

    except httpx.TimeoutException:
        return AuthResult(success=False, error="OAuth request timed out")
    except Exception as e:
        logger.warning(f"OAuth callback error for {provider}: {e}")
        return AuthResult(success=False, error="OAuth callback failed")


def _parse_userinfo(provider: str, data: Dict[str, Any]) -> AuthUser:
    if provider == "google":
        return AuthUser(
            provider="google",
            sub=data.get("id", data.get("sub", "")),
            name=data.get("name", ""),
            email=data.get("email", ""),
            avatar_url=data.get("picture", ""),
        )
    elif provider == "github":
        return AuthUser(
            provider="github",
            sub=str(data.get("id", "")),
            name=data.get("name", data.get("login", "")),
            email=data.get("email", ""),
            avatar_url=data.get("avatar_url", ""),
        )
    return AuthUser(provider=provider, sub=str(data.get("id", "")))


# ── Gateway authorization ──────────────────────────────────────────

def get_allowed_users() -> Dict[str, List[str]]:
    """Load allowed user IDs from environment for chat gateway adapters."""
    perms: Dict[str, List[str]] = {}
    platforms = [
        "telegram", "discord", "whatsapp", "facebook", "instagram",
        "slack", "signal", "matrix", "mattermost", "email", "sms",
    ]
    for platform in platforms:
        env_val = os.getenv(f"ALLOWED_{platform.upper()}_IDS", "").strip()
        if env_val:
            perms[platform] = [i.strip() for i in env_val.split(",") if i.strip()]
        else:
            perms[platform] = []
    return perms


def is_gateway_authorized(platform: str, sender_id: str) -> bool:
    """Check if the gateway sender is authorized."""
    allowed = get_allowed_users().get(platform, [])
    return "*" in allowed or sender_id in allowed


# ── FastAPI helpers ────────────────────────────────────────────────

PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/token",
    "/api/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
}

if os.environ.get("NEXUS_PUBLIC_OPENAI_COMPAT", "false").lower() == "true":
    PUBLIC_PATHS.update({"/v1/models", "/v1/chat/completions"})


def is_public_path(path: str) -> bool:
    """Check if a path is publicly accessible (no auth required)."""
    if path in PUBLIC_PATHS:
        return True
    if path.startswith(("/docs/", "/openapi/", "/redoc/")):
        return True
    return False


def get_session_user(request) -> Optional[AuthUser]:
    """Extract AuthUser from Starlette session, if any."""
    try:
        session = request.session
    except (AssertionError, AttributeError):
        return None
    if session and "user" in session:
        return AuthUser(**session["user"])
    return None


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})


def is_loopback_request(request) -> bool:
    """True only when the peer address is a genuine loopback address.

    Anything we cannot positively identify as loopback is treated as remote.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not isinstance(host, str):
        return False
    return host.strip().lower() in _LOOPBACK_HOSTS


def check_auth(request) -> Optional[AuthUser]:
    """Check auth via session cookie first, then Authorization header.

    Returns AuthUser if authenticated, None otherwise.
    """
    # 1. Try session cookie
    user = get_session_user(request)
    if user is not None:
        return user

    # 2. Try Authorization header (case-insensitive header lookup)
    auth_header = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if validate_dashboard_token(token):
            return AuthUser(provider="token", sub="dashboard", name="Token User")

    # 3. Anonymous local access: opt-in AND restricted to loopback peers.
    #    Without the loopback check this flag silently disabled auth for every
    #    client that could reach the port (LAN, tunnels, container bridges).
    if os.environ.get("NEXUS_ALLOW_LOCAL_ANON", "false").lower() == "true" and is_loopback_request(request):
        return AuthUser(provider="local", sub="dashboard", name="Local User")
    return None
