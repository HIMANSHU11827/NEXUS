import os
from typing import Dict, List

# Load environment variable for dashboard token validation
_AUTH_TOKEN = os.environ.get("NEXUS_DASHBOARD_TOKEN", "").strip()

def get_allowed_users() -> Dict[str, List[str]]:
    """Load allowed user IDs from environment for chat gateway adapters."""
    perms = {}
    for platform in ["telegram", "discord", "whatsapp", "facebook", "instagram"]:
        env_val = os.getenv(f"ALLOWED_{platform.upper()}_IDS", "").split(",")
        perms[platform] = [i.strip() for i in env_val if i.strip()]
    return perms

def is_gateway_authorized(platform: str, sender_id: str) -> bool:
    """Check if the gateway sender is authorized."""
    allowed = get_allowed_users().get(platform, [])
    return "*" in allowed or sender_id in allowed

def validate_dashboard_token(token: str) -> bool:
    """Validate the supplied token against the saved NEXUS_DASHBOARD_TOKEN."""
    if not _AUTH_TOKEN:
        return True
    return token == _AUTH_TOKEN
