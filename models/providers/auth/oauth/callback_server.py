import asyncio
import logging
from typing import Optional

logger = logging.getLogger("nexus.oauth.callback")

OAUTH_SUCCESS_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"/><title>Authentication successful</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#09090b;color:#fafafa;font-family:ui-sans-serif,system-ui,sans-serif}}
h1{{font-size:28px;margin:0 0 10px}} p{{color:#a1a1aa;font-size:15px;margin:0}}
</style></head>
<body><main><h1>{heading}</h1><p>{message}</p></main></body>
</html>"""

OAUTH_ERROR_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"/><title>Authentication failed</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#09090b;color:#fafafa;font-family:ui-sans-serif,system-ui,sans-serif}}
h1{{font-size:28px;margin:0 0 10px}} p{{color:#a1a1aa;font-size:15px;margin:0}}
</style></head>
<body><main><h1>{heading}</h1><p>{message}</p></main></body>
</html>"""


class OAuthCallbackResult:
    def __init__(self, code: str, state: str):
        self.code = code
        self.state = state


class CallbackServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 1455, callback_path: str = "/callback"):
        self.host = host
        self.port = port
        self.callback_path = callback_path
        self._server: Optional[asyncio.AbstractServer] = None
        self._result: Optional[OAuthCallbackResult] = None
        self._error: Optional[str] = None
        self._event = asyncio.Event()

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.host}:{self.port}{self.callback_path}"

    async def start(self, expected_state: str) -> None:
        self._event.clear()
        self._result = None
        self._error = None

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            request_data = await reader.readuntil(b"\r\n\r\n")
            request_text = request_data.decode("utf-8", errors="replace")

            first_line = request_text.split("\r\n")[0] if request_text else ""
            method = first_line.split(" ")[0] if first_line else ""

            url_part = first_line.split(" ")[1] if len(first_line.split(" ")) > 1 else "/"
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url_part)

            if method == "OPTIONS":
                writer.write(b"HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, OPTIONS\r\nAccess-Control-Allow-Headers: content-type\r\n\r\n")
                await writer.drain()
                writer.close()
                return

            if parsed.path != self.callback_path:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nNot found")
                await writer.drain()
                writer.close()
                return

            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            error = params.get("error", [None])[0]

            if error:
                self._error = error
                body = OAUTH_ERROR_HTML.format(heading="Authentication failed", message=f"Error: {error}")
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\n\r\n{body}"
                writer.write(resp.encode())
                await writer.drain()
                writer.close()
                self._event.set()
                return

            if not code or not state:
                self._error = "Missing code or state in callback"
                body = "Missing code or state"
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n{body}"
                writer.write(resp.encode())
                await writer.drain()
                writer.close()
                self._event.set()
                return

            if state != expected_state:
                self._error = "State mismatch in OAuth callback"
                body = OAUTH_ERROR_HTML.format(heading="Authentication failed", message="State mismatch")
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\n\r\n{body}"
                writer.write(resp.encode())
                await writer.drain()
                writer.close()
                self._event.set()
                return

            self._result = OAuthCallbackResult(code=code, state=state)
            body = OAUTH_SUCCESS_HTML.format(heading="Authentication successful", message="You can close this window.")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\n\r\n{body}"
            writer.write(resp.encode())
            await writer.drain()
            writer.close()
            self._event.set()

        self._server = await asyncio.start_server(handler, host=self.host, port=self.port)

    async def wait_for_callback(self, timeout: float = 300.0) -> Optional[OAuthCallbackResult]:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            if self._error:
                raise RuntimeError(f"OAuth error: {self._error}")
            return self._result
        except asyncio.TimeoutError:
            raise RuntimeError("OAuth callback timeout")

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


async def wait_for_local_oauth_callback(
    expected_state: str,
    port: int = 1455,
    host: str = "127.0.0.1",
    callback_path: str = "/callback",
    timeout: float = 300.0,
) -> OAuthCallbackResult:
    server = CallbackServer(host=host, port=port, callback_path=callback_path)
    try:
        await server.start(expected_state)
        result = await server.wait_for_callback(timeout=timeout)
        if result is None:
            raise RuntimeError("No OAuth callback received")
        return result
    finally:
        await server.close()


def parse_oauth_authorization_input(input_str: str) -> OAuthCallbackResult:
    from urllib.parse import parse_qs, urlparse
    value = input_str.strip()
    if not value:
        raise ValueError("No input provided")

    if "#" in value and "://" not in value:
        parts = value.split("#", 2)
        return OAuthCallbackResult(code=parts[0], state=parts[1] if len(parts) > 1 else "")

    if "://" in value:
        try:
            parsed = urlparse(value)
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            if not code:
                raise ValueError("Missing 'code' parameter in URL")
            if not state:
                raise ValueError("Missing 'state' parameter in URL")
            return OAuthCallbackResult(code=code, state=state)
        except ValueError:
            raise
        except Exception:
            logger.warning("providers/oauth/callback_server.py:172 : suppressed error", exc_info=True)
            pass

    if "code=" in value:
        params = parse_qs(value)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            return OAuthCallbackResult(code=code, state=state or "")

    return OAuthCallbackResult(code=value, state="")
