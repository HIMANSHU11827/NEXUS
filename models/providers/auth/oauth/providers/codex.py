import base64
import json
import logging

from models.providers.auth.oauth.callback_server import (
    parse_oauth_authorization_input,
    wait_for_local_oauth_callback,
)
from models.providers.auth.oauth.expiry import resolve_oauth_expires_at
from models.providers.auth.oauth.pkce import generate_oauth_state, generate_pkce
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.codex")

# Public Codex/ChatGPT OAuth client (OpenClaw openai-chatgpt-oauth-*).
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
SCOPES = "openid profile email offline_access"


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


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
    # Best-effort account identity from the access-token JWT (OpenClaw resolves
    # accountId from the token before persisting credentials).
    account_id = _decode_jwt_payload(access_token).get("sub")
    return OAuthCredentials(
        access=access_token,
        refresh=refresh_token,
        expires=resolve_oauth_expires_at(expires_in),
        account_id=account_id,
    )


async def login_codex(
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
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": expected_state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "nexus",
    }
    url = f"{AUTHORIZE_URL}?{urlencode(auth_params)}"

    on_auth(OAuthAuthInfo(url=url, instructions="Complete login in your browser."))

    code = None
    try:
        result = await wait_for_local_oauth_callback(
            expected_state=expected_state,
            port=CALLBACK_PORT,
            callback_path=CALLBACK_PATH,
        )
        code = result.code
    except Exception as exc:
        logger.warning("codex.py: callback server unavailable: %s", exc)

    if not code and on_manual_code_input:
        manual = await on_manual_code_input()
        if manual:
            parsed = parse_oauth_authorization_input(manual)
            if parsed.state and parsed.state != expected_state:
                raise RuntimeError("OAuth state mismatch - possible CSRF attack")
            code = parsed.code

    if not code:
        input_text = await on_prompt("Paste the authorization code or full redirect URL:")
        parsed = parse_oauth_authorization_input(input_text)
        if parsed.state and parsed.state != expected_state:
            raise RuntimeError("OAuth state mismatch - possible CSRF attack")
        code = parsed.code

    if not code:
        raise RuntimeError("Missing authorization code")

    on_progress("Exchanging authorization code for tokens...")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return _parse_credentials(data)


def refresh_codex_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """Refresh the OAuth token using the refresh token."""
    import httpx

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh,
            "client_id": CLIENT_ID,
        },
    )
    response.raise_for_status()
    data = response.json()

    return _parse_credentials(data)