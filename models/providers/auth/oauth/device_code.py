import asyncio
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    interval_ms: float = 5000.0
    expires_at: float = 0.0


async def start_device_flow(
    url: str,
    client_id: str,
    scope: str = "read:user",
    signal: Optional[asyncio.Event] = None,
    extra: Optional[dict] = None,
) -> DeviceCodeResponse:
    import httpx
    payload = {"client_id": client_id, "scope": scope}
    if extra:
        payload.update(extra)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            data=payload,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    device_code: str = data["device_code"]
    user_code: str = data["user_code"]
    verification_uri: str = data["verification_uri"]
    interval: int = data.get("interval", 5)
    expires_in: int = data.get("expires_in", 900)

    return DeviceCodeResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=data.get("verification_uri_complete"),
        interval_ms=interval * 1000,
        expires_at=time.time() + expires_in,
    )


async def poll_for_token(
    url: str,
    client_id: str,
    device_code: str,
    interval_ms: float,
    expires_at: float,
    signal: Optional[asyncio.Event] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Poll the device-code token endpoint; returns the full token response dict."""
    import httpx
    deadline = expires_at
    polling_interval = max(1.0, interval_ms / 1000)

    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            if signal and signal.is_set():
                raise RuntimeError("Login cancelled")

            await asyncio.sleep(polling_interval)
            payload = {
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
            if extra:
                payload.update(extra)
            resp = await client.post(
                url,
                data=payload,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("access_token"):
                return data

            error = data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                # slow_down is cumulative; a returned interval raises but never
                # lowers the required polling floor.
                polling_interval += 5
                interval = data.get("interval")
                if isinstance(interval, (int, float)) and interval > 0:
                    polling_interval = max(polling_interval, float(interval))
                continue
            elif error == "expired_token":
                raise RuntimeError("Device code expired. Re-run the login.")
            elif error in ("access_denied", "authorization_denied"):
                raise RuntimeError("Device authorization was denied")
            else:
                desc = data.get("error_description", "")
                raise RuntimeError(f"Device flow failed: {error}{': ' + desc if desc else ''}")

    raise RuntimeError("Device flow timed out")