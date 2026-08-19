import base64
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

from models.providers.auth.oauth.device_code import poll_for_token, start_device_flow
from models.providers.auth.oauth.types import OAuthAuthInfo, OAuthCredentials

CLIENT_ID = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()
PUBLIC_GITHUB_COPILOT_DOMAIN = "github.com"
# Data-residency GHE tenant root (`<tenant>.ghe.com`, single label). GitHub
# defines a GHE.com enterprise as a dedicated SUBDOMAIN.ghe.com domain; nested
# hosts and bare `ghe.com` are not tenants.
GHE_DATA_RESIDENCY_HOST = re.compile(r"^[a-z0-9-]+\.ghe\.com$")
PUBLIC_COPILOT_TOKEN_URL = "https://api.individual.githubcopilot.com/copilot_internal/v2/token"

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


def is_supported_domain(domain: Optional[str]) -> bool:
    if not domain:
        return True
    if not re.match(r"^[a-z0-9.-]+$", domain):
        return False
    return domain == PUBLIC_GITHUB_COPILOT_DOMAIN or bool(GHE_DATA_RESIDENCY_HOST.match(domain))


def require_supported_domain(raw: str) -> str:
    domain = normalize_domain(raw)
    if not domain or not is_supported_domain(domain):
        raise RuntimeError(
            f'Unsupported GitHub Copilot domain "{raw}". Use github.com or a *.ghe.com data-residency tenant.'
        )
    return domain.lower()


def get_urls(domain: str = "github.com") -> dict:
    domain = require_supported_domain(domain)
    if domain == PUBLIC_GITHUB_COPILOT_DOMAIN:
        copilot_token_url = PUBLIC_COPILOT_TOKEN_URL
    else:
        copilot_token_url = f"https://{domain}/copilot_internal/v2/token"
    return {
        "device_code_url": f"https://{domain}/login/device/code",
        "access_token_url": f"https://{domain}/login/oauth/access_token",
        "verification_url": f"https://{domain}/login/device",
        "copilot_token_url": copilot_token_url,
    }


def get_base_url_from_token(token: str) -> Optional[str]:
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


def refresh_github_copilot_token(credentials: OAuthCredentials) -> OAuthCredentials:
    """Exchange the stored GitHub OAuth access token for a fresh Copilot token."""
    import httpx

    github_access_token = credentials.refresh
    if not github_access_token:
        raise RuntimeError("GitHub Copilot credential is missing the GitHub access token")
    enterprise_domain = credentials.enterprise_url
    if enterprise_domain and not is_supported_domain(enterprise_domain):
        raise RuntimeError(
            f'Refusing to refresh GitHub Copilot OAuth for unsupported enterprise domain "{enterprise_domain}". '
            "Re-authenticate with github.com or a *.ghe.com tenant."
        )
    domain = enterprise_domain or "github.com"
    copilot_token_url = get_urls(domain)["copilot_token_url"]

    resp = httpx.get(
        copilot_token_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {github_access_token}",
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
        refresh=github_access_token,
        expires=expires_at * 1000 if isinstance(expires_at, (int, float)) else time.time() * 1000 + 3600000,
        enterprise_url=enterprise_domain,
    )


async def login_github_copilot(
    on_auth,
    on_prompt,
    on_progress=None,
    signal=None,
) -> OAuthCredentials:
    enterprise_domain: Optional[str] = None
    env_domain = os.environ.get("COPILOT_GITHUB_DOMAIN", "").strip()
    if env_domain:
        enterprise_domain = require_supported_domain(env_domain)
    else:
        input_text = await on_prompt("GitHub Enterprise URL/domain (blank for github.com):")
        if input_text.strip():
            enterprise_domain = require_supported_domain(input_text)
    domain = enterprise_domain or PUBLIC_GITHUB_COPILOT_DOMAIN

    urls = get_urls(domain)
    device = await start_device_flow(urls["device_code_url"], CLIENT_ID, scope="read:user")

    on_auth(OAuthAuthInfo(url=urls["verification_url"], instructions=f"Enter code: {device.user_code}"))

    response = await poll_for_token(
        urls["access_token_url"],
        CLIENT_ID,
        device.device_code,
        device.interval_ms,
        device.expires_at,
    )
    github_access_token = response.get("access_token")
    if not github_access_token:
        raise RuntimeError("GitHub device flow returned no access_token")

    on_progress("Exchanging GitHub token for Copilot token...")

    return refresh_github_copilot_token(
        OAuthCredentials(
            access="",
            refresh=github_access_token,
            expires=time.time() * 1000,
            enterprise_url=enterprise_domain,
        )
    )


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