"""Optional OpenRouter free-router smoke test.

This script verifies that the local OPENROUTER_API_KEY can reach the documented
OpenRouter free-model router. It is intentionally outside the normal test suite
because it performs a real network call and depends on the operator's key/quota.
"""

from __future__ import annotations

import json
import os
import sys

import requests


def main() -> int:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or "your_" in api_key.lower() or "YOUR_" in api_key:
        print("OPENROUTER_API_KEY is missing. Set it in your environment or local .env.")
        return 2

    model = os.getenv("NEXUS_OPENROUTER_TEST_MODEL", "openrouter/free").strip() or "openrouter/free"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: NEXUS_OPENROUTER_OK"}],
        "max_tokens": 16,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://nexus-ai-os.com",
        "X-Title": "Nexus AI OS",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=int(os.getenv("NEXUS_PROVIDER_TIMEOUT", "30")),
        )
    except requests.RequestException as exc:
        print(f"OpenRouter request failed: {exc}")
        return 1

    if response.status_code != 200:
        print(f"OpenRouter returned HTTP {response.status_code}: {response.text[:500]}")
        return 1

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(json.dumps({"model": model, "response": content.strip()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
