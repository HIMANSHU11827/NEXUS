import asyncio
import email
import logging
import os
from typing import Optional

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

try:
    import aiosmtplib
    from aioimaplib import IMAP4_SSL
    HAS_EMAIL_LIBS = True
except ImportError:
    HAS_EMAIL_LIBS = False
    logger.warning("aiosmtplib/aioimaplib not installed. Install with: pip install aiosmtplib aioimaplib")


class EmailAdapter(BasePlatformAdapter):
    """
    NEXUS Email/SMTP Adapter.
    Sends via SMTP (aiosmtplib) and polls via IMAP (aioimaplib).
    Expects SMTP_* and IMAP_* environment vars.
    """
    name = "email"

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 0,
        smtp_user: str = "",
        smtp_pass: str = "",
        imap_host: str = "",
        imap_port: int = 0,
        imap_user: str = "",
        imap_pass: str = "",
        from_addr: str = "",
    ):
        super().__init__("email")
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER", "")
        self.smtp_pass = smtp_pass or os.getenv("SMTP_PASS", "")
        self.imap_host = imap_host or os.getenv("IMAP_HOST", "imap.gmail.com")
        self.imap_port = imap_port or int(os.getenv("IMAP_PORT", "993"))
        self.imap_user = imap_user or os.getenv("IMAP_USER", "") or self.smtp_user
        self.imap_pass = imap_pass or os.getenv("IMAP_PASS", "") or self.smtp_pass
        self.from_addr = from_addr or os.getenv("EMAIL_FROM", "") or self.smtp_user
        self._imap: Optional[IMAP4_SSL] = None
        self._poll_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        if not HAS_EMAIL_LIBS:
            logger.error("aiosmtplib/aioimaplib not available")
            return False
        if not self.smtp_user or not self.smtp_pass:
            logger.error("SMTP_USER and SMTP_PASS must be set")
            return False

        try:
            if self.imap_user and self.imap_pass:
                self._imap = IMAP4_SSL(host=self.imap_host, port=self.imap_port)
                await self._imap.wait_hello_from_server()
                await self._imap.login(self.imap_user, self.imap_pass)
                await self._imap.select("INBOX")
                self._poll_task = asyncio.create_task(self._poll_inbox())

            return True
        except Exception as e:
            logger.error(f"Email connection failed: {e}")
            return False

    async def disconnect(self):
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        if self._imap:
            try:
                await self._imap.logout()
            except Exception:
                logger.warning("gateway/platforms/email.py:81 async disconnect: suppressed error", exc_info=True)
                pass
            self._imap = None

    async def _poll_inbox(self):
        """Poll IMAP inbox for new messages."""
        while True:
            try:
                status, ids = await self._imap.search("(UNSEEN)")
                if status == "OK" and ids[0]:
                    for mid in ids[0].split():
                        status, data = await self._imap.fetch(mid, "(RFC822)")
                        if status == "OK":
                            raw_email = data[0][1]
                            await self._process_incoming(raw_email, mid)
                        await self._imap.store(mid, "+FLAGS", "\\Seen")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"IMAP poll error: {e}")
            await asyncio.sleep(15)

    async def _process_incoming(self, raw: bytes, uid: bytes):
        if not self._on_message:
            return
        try:
            msg = email.message_from_bytes(raw)
            subject = msg.get("Subject", "")
            sender = msg.get("From", "")
            text_body = ""

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        text_body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                text_body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            if text_body:
                event = MessageEvent(
                    text=text_body.strip(),
                    sender_id=sender,
                    chat_id=sender,
                    platform="email",
                    message_id=uid.decode() if isinstance(uid, bytes) else str(uid),
                )
                await self._on_message(event)
        except Exception as e:
            logger.debug(f"Email parse error: {e}")

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not HAS_EMAIL_LIBS:
            return SendResult(success=False, error="Email libs not available")

        try:
            message = email.message.EmailMessage()
            message["From"] = self.from_addr
            message["To"] = chat_id
            message["Subject"] = "NEXUS AI"
            if reply_to:
                message["In-Reply-To"] = reply_to
                message["Subject"] = f"Re: {reply_to}"
            message.set_content(text)

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_pass,
                use_tls=self.smtp_port == 465,
                start_tls=self.smtp_port == 587,
            )
            return SendResult(success=True, message_id=message["Message-ID"])
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        pass
