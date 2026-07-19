import base64
import os
import time

from providers.oauth.device_code import poll_for_token, start_device_flow
from providers.oauth.types import OAuthCredentials

_CLIENT_ID_ENV = os.environ.get("NEXUS_MINIMAX_CLIENT_ID") or ""
CLIENT_ID = _CLIENT_ID_ENV if _CLIENT_ID_ENV else base64.b64decode("WU9VUl9NSU5JTUFYX0NMSUVOVF9JRA==").decode()
DEVICE_CODE_URL = "https://auth.minimaxi.com/oauth/device/code"
ACCESS_TOKEN_URL = "https://auth.minimaxi.com/oauth/token"
SCOPES = "openai"


async def login_minimax(
    on_auth,
    on_prompt,
    on_progress=None,
    signal=None,
) -> OAuthCredentials:
    device = await start_device_flow(DEVICE_CODE_URL, CLIENT_ID, scope=SCOPES)

    on_auth(device.verification_uri, f"Enter code: {device.user_code}")

    access_token = await poll_for_token(
        ACCESS_TOKEN_URL,
        CLIENT_ID,
        device.device_code,
        device.interval_ms,
        device.expires_at,
    )

    return OAuthCredentials(
        access=access_token,
        refresh=access_token,
        expires=time.time() * 1000 + 86400000,
    )


async def refresh_minimax_token(refresh_token: str) -> OAuthCredentials:
    return OAuthCredentials(
        access=refresh_token,
        refresh=refresh_token,
        expires=time.time() * 1000 + 86400000,
    )
