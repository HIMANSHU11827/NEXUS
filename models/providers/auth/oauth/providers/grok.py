import asyncio
import base64
import json
import logging
import time

from models.providers.auth.oauth.expiry import resolve_oauth_expires_at
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

logger = logging.getLogger("nexus.oauth.grok")

# Public xAI OAuth client used by Grok CLI (OpenClaw xai-oauth.ts).
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPES = "openid profile email offline_access grok-cli:access api:access"
ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
SLOW_DOWN_INCREMENT_MS = 5000
REFRESH_MAX_ATTEMPTS = 3
REFRESH_RETRY_DELAY_MS = 250


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


def _is_trusted_xai_endpoint(endpoint: str) -> bool:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(endpoint)
        return parsed.scheme == "https" and (parsed.hostname == "x.ai" or parsed.hostname.endswith(".x.ai"))
    except Exception:
        return False


def _require_trusted_xai_endpoint(endpoint: str, label: str) -> str:
    if not _is_trusted_xai_endpoint(endpoint):
        raise RuntimeError(f"xAI OAuth discovery returned untrusted {label}")
    return endpoint


async def _fetch_xai_discovery() -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(DISCOVERY_URL, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


def _parse_token(data: dict) -> OAuthCredentials:
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("xAI token response is missing access_token")
    refresh_token = data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError(
            "xAI token response is missing refresh_token. Re-run the login; "
            "the OAuth client may not be configured to issue refresh tokens "
            "(commonly because the offline_access scope was rejected)."
        )
    expires_in = data.get("expires_in")
    expires = resolve_oauth_expires_at(expires_in) if expires_in is not None else None
    if expires is None:
        # RFC 6749 expires_in preferred; the access-token JWT exp is the only
        # legitimate fallback (id_token exp reflects the OIDC session, not the
        # access token).
        expires = _decode_jwt_payload(access_token).get("exp")
        if expires is not None:
            expires = float(expires) * 1000 - 5 * 60 * 1000
    if expires is None:
        raise RuntimeError("xAI token response is missing expires_in")

    identity = _decode_jwt_payload(data.get("id_token") or access_token)
    return OAuthCredentials(
        access=access_token,
        refresh=refresh_token,
        expires=expires,
        email=identity.get("email"),
        account_id=identity.get("sub"),
    )


async def login_grok(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    import httpx

    discovery = await _fetch_xai_discovery()
    device_endpoint = _require_trusted_xai_endpoint(
        discovery.get("device_authorization_endpoint", ""), "device authorization endpoint"
    )
    token_endpoint = _require_trusted_xai_endpoint(
        discovery.get("token_endpoint", ""), "token endpoint"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            device_endpoint,
            data={"client_id": CLIENT_ID, "scope": SCOPES},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    device_code = data.get("device_code")
    user_code = data.get("user_code")
    verification_uri = data.get("verification_uri")
    if not device_code or not user_code or not verification_uri:
        raise RuntimeError("xAI device code response is missing device_code, user_code, or verification_uri")
    if not _is_trusted_xai_endpoint(verification_uri):
        raise RuntimeError("xAI device code response returned an untrusted verification URI")
    verification_uri_complete = data.get("verification_uri_complete")
    if verification_uri_complete and not _is_trusted_xai_endpoint(verification_uri_complete):
        raise RuntimeError("xAI device code response returned an untrusted complete verification URI")

    expires_in = data.get("expires_in", 900)
    interval = data.get("interval", 5)
    deadline = time.time() + float(expires_in)
    interval_ms = max(1000.0, float(interval) * 1000)

    browser_url = verification_uri_complete or verification_uri
    on_auth(OAuthAuthInfo(
        url=browser_url,
        instructions=f"Enter code: {user_code} (expires in {int(expires_in) // 60} minutes).",
    ))
    on_progress("Waiting for xAI device authorization...")

    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            if signal and signal.is_set():
                raise RuntimeError("Login cancelled")
            await asyncio.sleep(interval_ms / 1000)

            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": DEVICE_CODE_GRANT_TYPE,
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

            if body.get("access_token"):
                creds = _parse_token(body)
                creds.extra["token_endpoint"] = token_endpoint
                creds.extra["issuer"] = ISSUER
                creds.extra["authFlow"] = "device-code"
                return creds

            error = body.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval_ms += SLOW_DOWN_INCREMENT_MS
                continue
            if error in ("access_denied", "authorization_denied"):
                raise RuntimeError("xAI device authorization was denied")
            if error == "expired_token":
                raise RuntimeError("xAI device code expired. Re-run the login.")
            desc = body.get("error_description", "")
            raise RuntimeError(f"xAI device token exchange failed: {error}{': ' + desc if desc else ''}")

    raise RuntimeError("xAI device authorization timed out")


def refresh_grok_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """Refresh the xAI OAuth token; retries only Cloudflare HTML challenges."""
    import httpx

    cached = credentials.extra.get("token_endpoint")
    token_endpoint = cached if _is_trusted_xai_endpoint(cached or "") else _discover_sync("token_endpoint")

    last_error = "xAI OAuth refresh failed"
    for attempt in range(1, REFRESH_MAX_ATTEMPTS + 1):
        resp = httpx.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": credentials.refresh,
            },
            headers={"Accept": "application/json"},
        )
        body_text = resp.text or ""
        is_html_challenge = (
            "text/html" in resp.headers.get("content-type", "")
            or "<html" in body_text.lower()
            or resp.headers.get("cf-mitigated") == "challenge"
        )
        if resp.status_code < 400 and not is_html_challenge:
            data = resp.json()
            refreshed = _parse_token(data)
            refreshed.extra["token_endpoint"] = token_endpoint
            refreshed.extra["issuer"] = ISSUER
            return refreshed
        if not is_html_challenge:
            last_error = f"xAI OAuth refresh failed ({resp.status_code}): {body_text[:300]}"
            break
        if attempt < REFRESH_MAX_ATTEMPTS:
            time.sleep(REFRESH_RETRY_DELAY_MS / 1000)
            last_error = "xAI returned an HTML/Cloudflare challenge instead of OAuth JSON"

    raise RuntimeError(last_error)


def _discover_sync(endpoint_key: str) -> str:
    import httpx

    resp = httpx.get(DISCOVERY_URL, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return _require_trusted_xai_endpoint(resp.json().get(endpoint_key, ""), endpoint_key)