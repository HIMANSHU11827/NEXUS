"""NEXUS IRC Adapter.

A small, self-contained async IRC client (RFC 1459 / 2812 subset) built on
top of :mod:`asyncio` stream sockets. It does not require any third-party IRC
library, so the module is always importable and unit-testable; the network
transport is fully injectable for tests.

The adapter is **env-gated**: ``connect()`` returns ``False`` unless a nick is
configured (``IRC_NICK``). Incoming ``PRIVMSG`` lines are normalised into
``MessageEvent`` objects so the handler logic is testable without a live
server.

Environment variables
----------------------
``IRC_SERVER``          Server hostname (default: irc.libera.chat)
``IRC_PORT``            Server port (default: 6697 with TLS, else 6667)
``IRC_NICK``            Bot nick (**required** to enable the gateway)
``IRC_PASSWORD``        Server password / SASL or NickServ password (optional)
``IRC_CHANNELS``        Comma-separated channels to auto-join (optional)
``IRC_USE_SSL``         Force TLS on/off (``1/true/yes`` or ``0/false/no``)
``IRC_USERNAME``        USER ident (default: nick)
``IRC_REALNAME``        USER realname (default: "NEXUS AI")
"""

import asyncio
import logging
import os
import ssl
from typing import List, Optional

from gateway.base import BasePlatformAdapter, HEALTH_HEALTHY, HEALTH_UNAVAILABLE, MessageEvent, SendResult

logger = logging.getLogger(__name__)

# Channel prefix characters per RFC 2811.
_CHANNEL_PREFIXES = ("#", "&", "+", "!")

# Numeric replies that mean "nickname already in use" (433) or otherwise
# unacceptable (432 invalid, 436 temporarily unavailable).
_NICK_ERROR_REPLIES = {"432", "433", "436"}


class IRCAdapter(BasePlatformAdapter):
    """Self-contained async IRC gateway adapter."""

    name = "irc"

    def __init__(
        self,
        server: str = "",
        port: int = 0,
        nick: str = "",
        password: str = "",
        channels: Optional[List[str]] = None,
        use_ssl: Optional[bool] = None,
        username: str = "",
        realname: str = "",
    ):
        super().__init__("irc")
        self.server = server or os.getenv("IRC_SERVER", "irc.libera.chat")

        raw_port = int(port or os.getenv("IRC_PORT", "") or 0)
        env_ssl = os.getenv("IRC_USE_SSL", "").strip().lower()

        if use_ssl is not None:
            self.use_ssl = bool(use_ssl)
        elif env_ssl in ("1", "true", "yes", "on"):
            self.use_ssl = True
        elif env_ssl in ("0", "false", "no", "off"):
            self.use_ssl = False
        else:
            # Default TLS on when using the standard TLS port.
            self.use_ssl = raw_port == 6697

        self.port = raw_port or (6697 if self.use_ssl else 6667)

        self.nick = nick or os.getenv("IRC_NICK", "")
        self.password = password or os.getenv("IRC_PASSWORD", "")
        if channels is not None:
            self.channels = list(channels)
        else:
            self.channels = [
                c.strip()
                for c in os.getenv("IRC_CHANNELS", "").split(",")
                if c.strip()
            ]
        self.username = username or os.getenv("IRC_USERNAME", "") or (self.nick or "nexus")
        self.realname = realname or os.getenv("IRC_REALNAME", "") or "NEXUS AI"

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._read_task: Optional[asyncio.Task] = None
        self._nick_attempts = 0
        self.connected = False

    # ------------------------------------------------------------------ #
    # Configuration helpers
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True when a nick is available (the only hard requirement)."""
        return bool(self.nick)

    # ------------------------------------------------------------------ #
    # Networking
    # ------------------------------------------------------------------ #
    async def _open_connection(self):
        """Open the socket. Overridable in tests to inject fake streams."""
        ssl_ctx = ssl.create_default_context() if self.use_ssl else None
        return await asyncio.open_connection(self.server, self.port, ssl=ssl_ctx)

    async def _send_raw(self, line: str):
        if self._writer is None:
            raise RuntimeError("IRC not connected")
        self._writer.write((line + "\r\n").encode("utf-8", errors="replace"))
        await self._writer.drain()

    async def connect(self) -> bool:
        if not self.nick:
            logger.error("IRC_NICK not set — IRC adapter disabled")
            return False
        try:
            self._reader, self._writer = await self._open_connection()

            if self.password:
                await self._send_raw(f"PASS {self.password}")
            await self._send_raw(f"NICK {self.nick}")
            await self._send_raw(
                f"USER {self.username} 0 * :{self.realname}"
            )
            for channel in self.channels:
                await self._send_raw(f"JOIN {channel}")

            self.connected = True
            self._read_task = asyncio.ensure_future(self._read_loop())
            logger.info(
                "NEXUS IRC Adapter online as %s on %s:%s (ssl=%s)",
                self.nick, self.server, self.port, self.use_ssl,
            )
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"IRC connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._read_task = None

        if self._writer is not None:
            try:
                await self._send_raw("QUIT :NEXUS AI shutting down")
            except Exception:  # pragma: no cover - best effort
                pass
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._writer = None
            self._reader = None
        self.connected = False

    async def _read_loop(self):
        assert self._reader is not None, "read loop started without a reader"
        try:
            while True:
                raw = await self._reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                await self._handle_line(line)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # pragma: no cover - network dependent
            logger.debug(f"IRC read loop error: {e}")
        # EOF or a transport error ends the read loop. Report the adapter down
        # so the gateway supervisor schedules a reconnect; a stale "healthy"
        # flag would leave a dead socket invisible forever.
        self.connected = False
        self.health = HEALTH_UNAVAILABLE
        self.last_error = "IRC connection closed by server"

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    async def _handle_line(self, line: str):
        """Parse a single raw IRC line and dispatch the relevant handler."""
        # Server keep-alive / CAP negotiation.
        if line.startswith("PING"):
            # PING :token  ->  PONG :token
            token = line[4:].strip().lstrip(":")
            await self._send_raw(f"PONG :{token}")
            return

        # Split prefix (optional) from the rest.
        prefix: Optional[str] = None
        if line.startswith(":"):
            sp = line.find(" ")
            if sp == -1:
                return
            prefix = line[1:sp]
            rest = line[sp + 1:]
        else:
            rest = line

        # Split trailing (after " :") from the head.
        if " :" in rest:
            head, trailing = rest.split(" :", 1)
        else:
            head, trailing = rest, ""

        parts = head.split()
        if not parts:
            return
        command = parts[0].upper()
        params = parts[1:]

        if command == "PRIVMSG":
            target = params[0] if params else ""
            await self._on_privmsg(prefix, target, trailing)
        elif command in _NICK_ERROR_REPLIES:
            await self._handle_nick_in_use()

    @staticmethod
    def _nick_from_prefix(prefix: Optional[str]) -> str:
        """Extract the nick from an IRC ``nick!user@host`` prefix."""
        if not prefix:
            return ""
        return prefix.split("!")[0].split("@")[0]

    async def _on_privmsg(self, prefix: Optional[str], target: str, text: str):
        """Normalise a PRIVMSG into a NEXUS ``MessageEvent``."""
        if not self._on_message:
            return
        sender_id = self._nick_from_prefix(prefix) or (prefix or "")
        is_channel = bool(target) and target[0] in _CHANNEL_PREFIXES
        # Direct messages arrive with the sender as the target; use the sender
        # as the chat id so replies go back to the person, not ourselves.
        chat_id = target if is_channel else sender_id

        event = MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="irc",
            message_id=None,
            raw_data={"prefix": prefix, "target": target},
        )
        await self._on_message(event)

    async def _handle_nick_in_use(self):
        """Recover from a nick collision by appending an incrementing suffix."""
        self._nick_attempts += 1
        new_nick = f"{self.nick}_{self._nick_attempts}"
        logger.warning("IRC nick %s in use — trying %s", self.nick, new_nick)
        await self._send_raw(f"NICK {new_nick}")

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split_message(text: str) -> List[str]:
        """Split ``text`` into IRC-safe chunks (newlines + ~450-char limits)."""
        if not text:
            return [""]
        chunks: List[str] = []
        for raw_line in text.split("\n"):
            line = raw_line.rstrip("\r")
            if not line:
                continue
            # RFC 2812: keep well under the 512-byte command limit.
            while len(line.encode("utf-8", errors="replace")) > 450:
                cut = 450
                while cut > 0 and line[cut] not in (" ", "\t"):
                    cut -= 1
                if cut == 0:
                    cut = 450
                chunks.append(line[:cut])
                line = line[cut:]
            chunks.append(line)
        return chunks or [""]

    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._writer is None:
            return SendResult(success=False, error="Not connected")
        try:
            text = text or ""
            for chunk in self._split_message(text):
                await self._send_raw(f"PRIVMSG {chat_id} :{chunk}")
            return SendResult(success=True, message_id=None)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        """IRC has no typing indicator; no-op to satisfy the interface."""
        return None

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        """IRC has no native images — send the URL (with optional caption)."""
        text = f"{caption + chr(10) if caption else ''}{image_url}"
        return await self.send_text(chat_id, text)
