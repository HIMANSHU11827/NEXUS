import json
import logging
import os
from pathlib import Path

from models.providers.auth.oauth.expiry import resolve_oauth_expires_at
from models.providers.auth.oauth.types import OAuthCredentials

logger = logging.getLogger("nexus.oauth.gemini")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def adc_file_paths() -> list[Path]:
    paths: list[Path] = []
    env_path = os.environ.get("NEXUS_GEMINI_ADC_FILE", "").strip()
    if env_path:
        paths.append(Path(env_path))
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            paths.append(Path(appdata) / "gcloud" / "application_default_credentials.json")
    paths.append(Path.home() / ".config" / "gcloud" / "application_default_credentials.json")
    return paths


def _load_adc() -> dict:
    for path in adc_file_paths():
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Failed to parse Google ADC file {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise RuntimeError(f"Google ADC file {path} is not a JSON object")
            return data
    raise RuntimeError(
        "No Google application-default credentials found. Run `gcloud auth application-default login` "
        "(or set NEXUS_GEMINI_ADC_FILE to the credentials file path)."
    )


def _validate_adc(data: dict) -> None:
    missing = [key for key in ("client_id", "client_secret", "refresh_token") if not data.get(key)]
    if missing:
        raise RuntimeError(
            f"Google ADC file is missing required fields: {', '.join(missing)}. "
            "Run `gcloud auth application-default login` to regenerate it."
        )


def _exchange_refresh(adc: dict) -> dict:
    import httpx

    token_uri = adc.get("token_uri") or GOOGLE_TOKEN_URL
    response = httpx.post(
        token_uri,
        data={
            "grant_type": "refresh_token",
            "client_id": adc["client_id"],
            "client_secret": adc["client_secret"],
            "refresh_token": adc["refresh_token"],
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def _credentials_from_adc(adc: dict) -> OAuthCredentials:
    _validate_adc(adc)
    token = _exchange_refresh(adc)
    access_token = token.get("access_token")
    expires_in = token.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Google token response missing access_token")
    if expires_in is None:
        raise RuntimeError("Google token response missing expires_in")
    return OAuthCredentials(
        access=access_token,
        refresh=adc["refresh_token"],
        expires=resolve_oauth_expires_at(expires_in),
        email=adc.get("account"),
        account_id=adc.get("account"),
        extra={"project_id": adc.get("quota_project_id") or ""},
    )


async def login_gemini(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    """Import Google CLI (gcloud) application-default credentials.

    Matches OpenClaw's Gemini auth, which consumes the Google CLI's OAuth token
    instead of running a browser OAuth flow.
    """
    on_progress("Using Google CLI (gcloud) application-default credentials...")
    adc = _load_adc()
    return _credentials_from_adc(adc)


def refresh_gemini_token(credentials: OAuthCredentials) -> OAuthCredentials:
    adc = _load_adc()
    _validate_adc(adc)
    token = _exchange_refresh(adc)
    access_token = token.get("access_token")
    expires_in = token.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Google token response missing access_token")
    if expires_in is None:
        raise RuntimeError("Google token response missing expires_in")
    return OAuthCredentials(
        access=access_token,
        refresh=credentials.refresh or adc["refresh_token"],
        expires=resolve_oauth_expires_at(expires_in),
        email=credentials.email or adc.get("account"),
        account_id=credentials.account_id or adc.get("account"),
        extra={"project_id": adc.get("quota_project_id") or ""},
    )


def gemini_get_api_key(credentials: OAuthCredentials) -> str:
    """OAuth token encoded as the JSON credential shape the Gemini client parses."""
    project_id = (credentials.extra or {}).get("project_id", "")
    return json.dumps({"token": credentials.access, "projectId": project_id})