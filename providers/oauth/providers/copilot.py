import base64
import time
from typing import Optional
from urllib.parse import urlparse

from providers.oauth.device_code import poll_for_token, start_device_flow
from providers.oauth.types import OAuthCredentials

CLIENT_ID = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()
GITHUB_DEVICE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.individual.githubcopilot.com/copilot_internal/v2/token"

COPILOT_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}


def normalize_domain(input_str: str) -> Optional[str]:
    trimmed = input_str.strip()
    if not trimmed:
        return None
    try:
        if "://" not in trimmed:
            trimmed = "https://" + trimmed
        parsed = urlparse(trimmed)
        return parsed.hostname
    except Exception:
        return None


def get_urls(domain: str = "github.com") -> dict:
    return {
        "device_code_url": f"https://{domain}/login/device/code",
        "access_token_url": f"https://{domain}/login/oauth/access_token",
        "copilot_token_url": f"https://api.{domain}/copilot_internal/v2/token",
    }


def get_base_url_from_token(token: str) -> Optional[str]:
    import re
    match = re.search(r"proxy-ep=([^;]+)", token)
    if not match:
        return None
    proxy_host = match.group(1)
    api_host = proxy_host.replace("proxy.", "api.", 1)
    return f"https://{api_host}"


def get_github_copilot_base_url(token: Optional[str] = None, enterprise_domain: Optional[str] = None) -> str:
    if token:
        url = get_base_url_from_token(token)
        if url:
            return url
    if enterprise_domain:
        return f"https://copilot-api.{enterprise_domain}"
    return "https://api.individual.githubcopilot.com"


async def refresh_github_copilot_token(
    refresh_token: str,
    enterprise_domain: Optional[str] = None,
) -> OAuthCredentials:
    import httpx
    domain = enterprise_domain or "github.com"
    get_urls(domain)
    copilot_token_url = f"https://api.{domain}/copilot_internal/v2/token"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            copilot_token_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {refresh_token}",
                **COPILOT_HEADERS,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data.get("token")
    expires_at = data.get("expires_at")
    if not token or not expires_at:
        raise RuntimeError("Invalid Copilot token response fields")

    return OAuthCredentials(
        access=token,
        refresh=refresh_token,
        expires=expires_at * 1000 if isinstance(expires_at, (int, float)) else time.time() * 1000 + 3600000,
        enterprise_url=enterprise_domain,
    )


async def login_github_copilot(
    on_auth,
    on_prompt,
    on_progress=None,
    signal=None,
) -> OAuthCredentials:
    input_text = await on_prompt("GitHub Enterprise URL/domain (blank for github.com):")
    enterprise_domain = normalize_domain(input_text) if input_text.strip() else None
    domain = enterprise_domain or "github.com"

    urls = get_urls(domain)
    device = await start_device_flow(urls["device_code_url"], CLIENT_ID)

    on_auth(device.verification_uri, f"Enter code: {device.user_code}")

    github_access_token = await poll_for_token(
        urls["access_token_url"],
        CLIENT_ID,
        device.device_code,
        device.interval_ms,
        device.expires_at,
    )

    credentials = await refresh_github_copilot_token(github_access_token, enterprise_domain)
    return credentials


async def enable_github_copilot_model(
    token: str,
    model_id: str,
    enterprise_domain: Optional[str] = None,
) -> bool:
    import httpx
    base_url = get_github_copilot_base_url(token, enterprise_domain)
    url = f"{base_url}/models/{model_id}/policy"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    **COPILOT_HEADERS,
                    "openai-intent": "chat-policy",
                    "x-interaction-type": "chat-policy",
                },
                json={"state": "enabled"},
            )
            return resp.is_success
    except Exception:
        return False
