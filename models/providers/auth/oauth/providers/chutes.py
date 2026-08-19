import logging
import os

from models.providers.auth.oauth.callback_server import (
    parse_oauth_authorization_input,
    wait_for_local_oauth_callback,
)
from models.providers.auth.oauth.expiry import resolve_oauth_expires_at
from models.providers.auth.oauth.pkce import generate_oauth_state, generate_pkce
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.chutes")

CHUTES_AUTHORIZE_ENDPOINT = "https://api.chutes.ai/idp/authorize"
CHUTES_TOKEN_ENDPOINT = "https://api.chutes.ai/idp/token"
CHUTES_USERINFO_ENDPOINT = "https://api.chutes.ai/idp/userinfo"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:1456/oauth-callback"
DEFAULT_SCOPES = "openid profile chutes:invoke"


def _parse_redirect_uri(redirect_uri: str) -> tuple[str, int, str]:
    from urllib.parse import urlparse
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise RuntimeError(f"Chutes OAuth redirect URI must be http:// (got {redirect_uri})")
    hostname = parsed.hostname or "127.0.0.1"
    if hostname not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"Chutes OAuth redirect hostname must be loopback (got {hostname}). "
            "Use http://127.0.0.1:<port>/...")
    port = parsed.port or 80
    path = parsed.path or "/"
    return hostname, port, path


def _build_authorize_url(client_id: str, redirect_uri: str, scopes: list[str], state: str, challenge: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{CHUTES_AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def _parse_credentials(data: dict, now_ms: float) -> OAuthCredentials:
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Chutes token response returned no access_token")
    if expires_in is None:
        raise RuntimeError("Chutes token response returned invalid expires_in")
    return OAuthCredentials(
        access=access_token,
        refresh=refresh_token or "",
        expires=resolve_oauth_expires_at(expires_in, now=lambda: now_ms),
    )


async def _fetch_userinfo(client, access_token: str):
    try:
        resp = await client.get(
            CHUTES_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code < 400:
            return resp.json()
    except Exception:
        pass
    return None


async def login_chutes(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    import httpx
    import time

    client_id = os.environ.get("CHUTES_CLIENT_ID", "").strip()
    if not client_id:
        client_id = (await on_prompt("Enter Chutes OAuth client id")).strip()
    if not client_id:
        raise RuntimeError("Missing Chutes OAuth client id (set CHUTES_CLIENT_ID or enter it)")
    client_secret = os.environ.get("CHUTES_CLIENT_SECRET", "").strip() or None
    redirect_uri = os.environ.get("CHUTES_OAUTH_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    scopes = os.environ.get("CHUTES_OAUTH_SCOPES", "").strip() or DEFAULT_SCOPES
    scopes = [s for s in scopes.split() if s]

    hostname, port, path = _parse_redirect_uri(redirect_uri)
    verifier, challenge = generate_pkce()
    expected_state = generate_oauth_state()
    url = _build_authorize_url(client_id, redirect_uri, scopes, expected_state, challenge)

    on_auth(OAuthAuthInfo(url=url, instructions="Complete login in your browser."))

    code = None
    try:
        result = await wait_for_local_oauth_callback(
            expected_state=expected_state,
            port=port,
            callback_path=path,
        )
        code = result.code
    except Exception as exc:
        logger.warning("chutes.py: callback server unavailable: %s", exc)

    if not code and on_manual_code_input:
        manual = await on_manual_code_input()
        if manual:
            parsed = parse_oauth_authorization_input(manual)
            if parsed.state and parsed.state != expected_state:
                raise RuntimeError("Chutes OAuth state mismatch - possible CSRF attack. Please retry login.")
            code = parsed.code

    if not code:
        input_text = await on_prompt("Paste the Chutes redirect URL (must include code + state):")
        parsed = parse_oauth_authorization_input(input_text)
        if parsed.state and parsed.state != expected_state:
            raise RuntimeError("Chutes OAuth state mismatch - possible CSRF attack. Please retry login.")
        code = parsed.code

    if not code:
        raise RuntimeError("Missing Chutes OAuth code")

    on_progress("Exchanging code for tokens...")

    async with httpx.AsyncClient() as client:
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        if client_secret:
            payload["client_secret"] = client_secret
        resp = await client.post(CHUTES_TOKEN_ENDPOINT, data=payload, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()

    credentials = _parse_credentials(data, time.time() * 1000)
    if not credentials.refresh:
        raise RuntimeError("Chutes token exchange returned no refresh_token")
    credentials.extra["client_id"] = client_id

    info = await _fetch_userinfo(client, credentials.access)
    if isinstance(info, dict):
        credentials.email = info.get("username") or info.get("email")
        credentials.account_id = info.get("sub")

    return credentials


def refresh_chutes_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """Refresh a stored Chutes OAuth credential through the provider token endpoint."""
    import httpx
    import time

    if not credentials.refresh:
        raise RuntimeError("Chutes OAuth credential is missing refresh token")
    client_id = credentials.extra.get("client_id") or os.environ.get("CHUTES_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("Missing CHUTES_CLIENT_ID for Chutes OAuth refresh (set env var or re-auth).")
    client_secret = os.environ.get("CHUTES_CLIENT_SECRET", "").strip() or None

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": credentials.refresh,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    response = httpx.post(CHUTES_TOKEN_ENDPOINT, data=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    data = response.json()

    refreshed = _parse_credentials(data, time.time() * 1000)
    # RFC 6749 section 6 makes replacement refresh tokens optional.
    if not refreshed.refresh:
        refreshed.refresh = credentials.refresh
    refreshed.extra["client_id"] = client_id
    return refreshed