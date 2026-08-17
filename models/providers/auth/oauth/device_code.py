import asyncio
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval_ms: float
    expires_at: float


async def start_device_flow(
    url: str,
    client_id: str,
    scope: str = "read:user",
    signal: Optional[asyncio.Event] = None,
) -> DeviceCodeResponse:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            data={"client_id": client_id, "scope": scope},
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
) -> str:
    import httpx
    deadline = expires_at
    polling_interval = max(1.0, interval_ms / 1000)

    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            if signal and signal.is_set():
                raise RuntimeError("Login cancelled")

            await asyncio.sleep(polling_interval)
            resp = await client.post(
                url,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            access_token = data.get("access_token")
            if access_token:
                return access_token

            error = data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                polling_interval += 5
                interval = data.get("interval")
                if interval:
                    polling_interval = max(1.0, interval)
                continue
            else:
                desc = data.get("error_description", "")
                raise RuntimeError(f"Device flow failed: {error}{': ' + desc if desc else ''}")

    raise RuntimeError("Device flow timed out")
