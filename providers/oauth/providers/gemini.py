import time
import logging

from providers.oauth.callback_server import (
    parse_oauth_authorization_input,
    wait_for_local_oauth_callback,
)
from providers.oauth.pkce import generate_oauth_state, generate_pkce
from providers.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.gemini")

CLIENT_ID = "gemini"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALLBACK_PORT = 8085
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}{CALLBACK_PATH}"
SCOPES = "openai"


async def login_gemini(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    import httpx

    verifier, challenge = generate_pkce()
    expected_state = generate_oauth_state()

    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": expected_state,
    }

    from urllib.parse import urlencode
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
    except Exception:
        logger.warning("providers/oauth/providers/gemini.py: suppressed error in login_gemini", exc_info=True)
        pass

    if not code and on_manual_code_input:
        manual = await on_manual_code_input()
        if manual:
            parsed = parse_oauth_authorization_input(manual)
            code = parsed.code
            state = parsed.state or expected_state

    if not code:
        input_text = await on_prompt("Paste the authorization code or full redirect URL:")
        parsed = parse_oauth_authorization_input(input_text)
        code = parsed.code
        state = parsed.state or expected_state

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
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)

    return OAuthCredentials(
        access=access_token,
        refresh=refresh_token,
        expires=time.time() * 1000 + float(expires_in) * 1000,
    )


def refresh_gemini_token(refresh_token: str) -> OAuthCredentials:
    """Refresh the OAuth token using the refresh token."""
    import httpx

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    response.raise_for_status()
    data = response.json()

    return OAuthCredentials(
        access=data.get("access_token"),
        refresh=data.get("refresh_token", refresh_token),
        expires=time.time() * 1000 + float(data.get("expires_in", 3600)) * 1000,
    )

