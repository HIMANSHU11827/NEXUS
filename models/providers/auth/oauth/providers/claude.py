import logging
import time

from models.providers.auth.oauth.callback_server import (
    parse_oauth_authorization_input,
    wait_for_local_oauth_callback,
)
from models.providers.auth.oauth.expiry import resolve_oauth_expires_at
from models.providers.auth.oauth.pkce import generate_oauth_state, generate_pkce
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.claude")

# Public Anthropic OAuth client used by Claude Code (OpenClaw anthropic.ts).
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CALLBACK_PORT = 53692
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)


def _parse_credentials(data: dict) -> OAuthCredentials:
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Token response missing access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("Token response missing refresh_token")
    if expires_in is None:
        raise RuntimeError("Token response missing expires_in")
    return OAuthCredentials(
        access=access_token,
        refresh=refresh_token,
        expires=resolve_oauth_expires_at(expires_in),
    )


async def login_anthropic(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    import httpx

    verifier, challenge = generate_pkce()
    expected_state = generate_oauth_state()

    from urllib.parse import urlencode
    auth_params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": expected_state,
    }
    url = f"{AUTHORIZE_URL}?{urlencode(auth_params)}"

    on_auth(OAuthAuthInfo(url=url, instructions="Complete login in your browser."))

    code = None
    state = None
    try:
        result = await wait_for_local_oauth_callback(
            expected_state=expected_state,
            port=CALLBACK_PORT,
            callback_path=CALLBACK_PATH,
        )
        code = result.code
        state = result.state
    except Exception as exc:
        logger.warning("claude.py: callback server unavailable: %s", exc)

    if not code and on_manual_code_input:
        manual = await on_manual_code_input()
        if manual:
            parsed = parse_oauth_authorization_input(manual)
            if parsed.state and parsed.state != expected_state:
                raise RuntimeError("OAuth state mismatch - possible CSRF attack")
            code = parsed.code
            state = parsed.state or expected_state

    if not code:
        input_text = await on_prompt("Paste the authorization code or full redirect URL:")
        parsed = parse_oauth_authorization_input(input_text)
        if parsed.state and parsed.state != expected_state:
            raise RuntimeError("OAuth state mismatch - possible CSRF attack")
        code = parsed.code
        state = parsed.state or expected_state

    if not code:
        raise RuntimeError("Missing authorization code")
    if not state:
        raise RuntimeError("Missing OAuth state")

    on_progress("Exchanging authorization code for tokens...")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "state": state,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return _parse_credentials(data)


def refresh_anthropic_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """Refresh the OAuth token using the refresh token."""
    import httpx

    response = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": credentials.refresh,
        },
    )
    response.raise_for_status()
    data = response.json()

    return _parse_credentials(data)