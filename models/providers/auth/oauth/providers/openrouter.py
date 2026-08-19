import logging
import time

from models.providers.auth.oauth.callback_server import (
    parse_oauth_authorization_input,
    wait_for_local_oauth_callback,
)
from models.providers.auth.oauth.pkce import generate_oauth_state, generate_pkce
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.openrouter")

AUTHORIZE_URL = "https://openrouter.ai/auth"
TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 3000
CALLBACK_PATH = "/openrouter-oauth/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"
# OpenRouter OAuth issues an API key, not a rotating bearer token. The key has
# no expiry; this horizon only prevents pointless "refresh" attempts.
KEY_LIFETIME_MS = 10 * 365 * 24 * 3600 * 1000


def _build_authorize_url(challenge: str, state: str) -> str:
    from urllib.parse import quote
    callback_url = f"{REDIRECT_URI}?state={state}"
    return (
        f"{AUTHORIZE_URL}?callback_url={quote(callback_url, safe='')}"
        f"&code_challenge={quote(challenge, safe='')}"
        f"&code_challenge_method=S256"
    )


def _parse_credentials(data: dict) -> OAuthCredentials:
    key = data.get("key")
    if not isinstance(key, str) or not key:
        raise RuntimeError("OpenRouter OAuth key exchange returned no API key")
    user_id = data.get("user_id") or data.get("userId")
    return OAuthCredentials(
        access=key,
        refresh="",
        expires=time.time() * 1000 + KEY_LIFETIME_MS,
        account_id=user_id,
    )


async def login_openrouter(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    import httpx

    verifier, challenge = generate_pkce()
    expected_state = generate_oauth_state()
    url = _build_authorize_url(challenge, expected_state)

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
        logger.warning("openrouter.py: callback server unavailable: %s", exc)

    if not code and on_manual_code_input:
        manual = await on_manual_code_input()
        if manual:
            parsed = parse_oauth_authorization_input(manual)
            if parsed.state and parsed.state != expected_state:
                raise RuntimeError("OpenRouter OAuth state mismatch. Please retry login.")
            code = parsed.code

    if not code:
        input_text = await on_prompt("Paste the OpenRouter redirect URL:")
        parsed = parse_oauth_authorization_input(input_text)
        if parsed.state and parsed.state != expected_state:
            raise RuntimeError("OpenRouter OAuth state mismatch. Please retry login.")
        code = parsed.code

    if not code:
        raise RuntimeError("Missing OpenRouter OAuth code")

    on_progress("Exchanging OpenRouter OAuth code...")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            json={
                "code": code,
                "code_verifier": verifier,
                "code_challenge_method": "S256",
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    return _parse_credentials(data)


def refresh_openrouter_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """OpenRouter OAuth keys do not rotate; re-run login to issue a new key."""
    raise RuntimeError("OpenRouter OAuth keys do not rotate. Run `nexus auth login openrouter` to issue a new key.")