import asyncio
import logging
import time
import uuid

from models.providers.auth.oauth.pkce import generate_oauth_state, generate_pkce
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.minimax")

MINIMAX_OAUTH_CONFIG = {
    "cn": {
        "oauth_base_url": "https://account.minimaxi.com",
        "client_id": "78257093-7e40-4613-99e0-527b14b39113",
    },
    "global": {
        "oauth_base_url": "https://account.minimax.io",
        "client_id": "78257093-7e40-4613-99e0-527b14b39113",
    },
}
SCOPES = "group_id profile model.completion"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:user_code"
# Values below this are relative seconds; above it, absolute epoch milliseconds.
RELATIVE_EXPIRY_SECONDS_THRESHOLD = 1_000_000_000


def _config(region: str) -> dict:
    return MINIMAX_OAUTH_CONFIG.get(region, MINIMAX_OAUTH_CONFIG["global"])


def _normalize_expires(expired_in, now_ms: float) -> float:
    value = float(expired_in)
    if value < RELATIVE_EXPIRY_SECONDS_THRESHOLD:
        return now_ms + value * 1000 - 5 * 60 * 1000
    return value


async def login_minimax(
    on_auth,
    on_prompt,
    on_progress=None,
    signal=None,
    region: str = "global",
) -> OAuthCredentials:
    import httpx

    config = _config(region)
    code_endpoint = f"{config['oauth_base_url']}/oauth2/device/code"
    token_endpoint = f"{config['oauth_base_url']}/oauth2/token"
    client_id = config["client_id"]

    verifier, challenge = generate_pkce()
    state = generate_oauth_state()
    now_ms = time.time() * 1000

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            code_endpoint,
            data={
                "response_type": "code",
                "client_id": client_id,
                "scope": SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            },
            headers={"Accept": "application/json", "x-request-id": str(uuid.uuid4())},
        )
        resp.raise_for_status()
        data = resp.json()

    user_code = data.get("user_code")
    verification_uri = data.get("verification_uri")
    expired_in = data.get("expired_in")
    returned_state = data.get("state")
    if not user_code or not verification_uri or expired_in is None:
        raise RuntimeError("MiniMax OAuth authorization returned an incomplete payload (missing user_code or verification_uri)")
    if returned_state != state:
        raise RuntimeError("MiniMax OAuth state mismatch: possible CSRF attack or session corruption")
    expire_at_ms = _normalize_expires(expired_in, now_ms)
    interval_s = data.get("interval") or 2
    interval_ms = max(1000.0, float(interval_s) * 1000)

    on_auth(OAuthAuthInfo(url=verification_uri, instructions=f"Enter code: {user_code}"))

    while time.time() * 1000 < expire_at_ms:
        if signal and signal.is_set():
            raise RuntimeError("Login cancelled")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": GRANT_TYPE,
                    "client_id": client_id,
                    "user_code": user_code,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

        status = body.get("status")
        if status == "success":
            access_token = body.get("access_token")
            refresh_token = body.get("refresh_token")
            expired_in = body.get("expired_in")
            if not access_token or not refresh_token or expired_in is None:
                raise RuntimeError("MiniMax OAuth returned incomplete token payload.")
            credentials = OAuthCredentials(
                access=access_token,
                refresh=refresh_token,
                expires=_normalize_expires(expired_in, time.time() * 1000),
            )
            credentials.extra["region"] = region
            credentials.extra["authFlow"] = "user-code"
            return credentials
        if status == "pending":
            await asyncio.sleep(interval_ms / 1000)
            continue
        base_resp = body.get("base_resp") or {}
        message = base_resp.get("status_msg") if isinstance(base_resp, dict) else None
        raise RuntimeError(f"MiniMax OAuth failed: {message or body.get('status', 'unknown error')}")

    raise RuntimeError("MiniMax OAuth timed out before authorization completed.")


def refresh_minimax_token(credentials: OAuthCredentials) -> OAuthCredentials:
    import httpx

    config = _config(credentials.extra.get("region", "global"))
    token_endpoint = f"{config['oauth_base_url']}/oauth2/token"
    client_id = config["client_id"]

    response = httpx.post(
        token_endpoint,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": credentials.refresh,
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    body = response.json()

    status = body.get("status")
    if status == "success":
        access_token = body.get("access_token")
        refresh_token = body.get("refresh_token") or credentials.refresh
        expired_in = body.get("expired_in")
        if not access_token or expired_in is None:
            raise RuntimeError("MiniMax OAuth refresh returned an incomplete token payload.")
        refreshed = OAuthCredentials(
            access=access_token,
            refresh=refresh_token,
            expires=_normalize_expires(expired_in, time.time() * 1000),
        )
        refreshed.extra["region"] = credentials.extra.get("region", "global")
        refreshed.extra["authFlow"] = "user-code"
        return refreshed
    base_resp = body.get("base_resp") or {}
    message = base_resp.get("status_msg") if isinstance(base_resp, dict) else None
    raise RuntimeError(f"MiniMax OAuth refresh failed: {message or status or 'unknown error'}")