"""Shared OAuth expiry helpers (mirrors OpenClaw's provider-oauth-runtime)."""

import time

# Refresh 5 minutes before the token actually expires so request-time access
# never races an expiring token (OpenClaw: refreshSkewMs = 5 * 60 * 1000).
OAUTH_REFRESH_SKEW_MS = 5 * 60 * 1000


def resolve_oauth_expires_at(expires_in, now=None) -> float:
    """Absolute expiry in ms from a seconds-based ``expires_in``, minus the refresh skew."""
    now_ms = now() * 1000 if now else time.time() * 1000
    return now_ms + float(expires_in) * 1000 - OAUTH_REFRESH_SKEW_MS