import asyncio
import base64
import hashlib
import hmac
import logging
import os
from typing import Optional

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client as TwilioRestClient
    HAS_TWILIO = True
except ImportError:
    HAS_TWILIO = False
    logger.warning("twilio not installed. Install with: pip install twilio")

try:
    from flask import Flask, request
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None  # type: ignore
    request = None  # type: ignore

try:
    from werkzeug.serving import make_server
except ImportError:
    make_server = None  # type: ignore


def valid_twilio_signature(url: str, params, signature: str, auth_token: str) -> bool:
    """Validate a Twilio ``X-Twilio-Signature`` request header (constant-time).

    Twilio signs the request *url* concatenated with the alphabetically-sorted
    form params (key + value, no separators) using HMAC-SHA1 keyed on the
    account auth token, then base64-encodes the digest.
    """
    if not url or not auth_token or not signature:
        return False
    items = list(params.items()) if hasattr(params, "items") else list(params)
    signed = url + "".join(key + str(value) for key, value in sorted(items))
    digest = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    return hmac.compare_digest(digest, signature)


class SMSAdapter(BasePlatformAdapter):
    """
    NEXUS SMS Adapter.
    Uses Twilio API for sending/receiving SMS.
    Expects TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER.
    """
    name = "sms"

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        from_number: str = "",
    ):
        super().__init__("sms")
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = from_number or os.getenv("TWILIO_FROM_NUMBER", "")
        self._client: Optional[TwilioRestClient] = None
        self._webhook_server: Optional[asyncio.Task] = None
        self._webhook_http_server = None

    async def connect(self) -> bool:
        if not HAS_TWILIO:
            logger.error("twilio not available")
            return False
        if not self.account_sid or not self.auth_token or not self.from_number:
            logger.error("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER must be set")
            return False

        try:
            self._client = TwilioRestClient(self.account_sid, self.auth_token)

            self._webhook_server = asyncio.create_task(self._run_webhook())
            return True
        except Exception as e:
            logger.error(f"SMS/Twilio connection failed: {e}")
            return False

    async def disconnect(self):
        http_server = self._webhook_http_server
        self._webhook_http_server = None
        if http_server is not None:
            try:
                http_server.shutdown()
            except Exception:
                logger.debug("SMS webhook server shutdown failed", exc_info=True)
        webhook_task = self._webhook_server
        self._webhook_server = None
        await self._cancel_task(webhook_task)
        self._client = None

    async def _run_webhook(self):
        """Run a lightweight webhook server to receive SMS replies."""
        if not HAS_FLASK:
            logger.warning("Flask not installed — cannot run SMS webhook server for incoming messages")
            return
        if make_server is None:
            logger.warning("Werkzeug server unavailable — cannot run SMS webhook server")
            return

        loop = asyncio.get_running_loop()
        app = Flask(__name__)

        @app.route("/sms", methods=["POST"])
        def sms_webhook():
            signature = request.headers.get("X-Twilio-Signature", "")
            if not valid_twilio_signature(request.url, request.form, signature, self.auth_token):
                logger.warning("Rejecting SMS webhook: invalid/missing X-Twilio-Signature")
                return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>', 403, {"Content-Type": "text/xml"}

            from_number = request.form.get("From", "")
            body = request.form.get("Body", "")
            msg_sid = request.form.get("MessageSid", "")

            if body and from_number and self._on_message:
                event = MessageEvent(
                    text=body,
                    sender_id=from_number,
                    chat_id=from_number,
                    platform="sms",
                    message_id=msg_sid,
                )
                future = asyncio.run_coroutine_threadsafe(self._on_message(event), loop)

                def _report_dispatch_failure(done):
                    try:
                        done.result()
                    except Exception:
                        logger.warning("SMS webhook event dispatch failed", exc_info=True)

                future.add_done_callback(_report_dispatch_failure)

            return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>", 200, {"Content-Type": "text/xml"}

        port = int(os.getenv("TWILIO_WEBHOOK_PORT", "8081"))
        logger.info(f"SMS webhook listening on port {port}")
        server = make_server("0.0.0.0", port, app, threaded=True)
        self._webhook_http_server = server
        try:
            await asyncio.to_thread(server.serve_forever)
        finally:
            try:
                server.server_close()
            except Exception:
                logger.debug("SMS webhook server close failed", exc_info=True)
            if self._webhook_http_server is server:
                self._webhook_http_server = None

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            kwargs = {
                "to": chat_id,
                "from_": self.from_number,
                "body": text,
            }
            # reply_to was previously forwarded as ``status_callback``, which
            # Twilio interprets as a webhook URL — a message-id here always
            # fails or fires an invalid endpoint. SMS has no reply semantics;
            # drop it.
            message = await asyncio.to_thread(self._client.messages.create, **kwargs)
            return SendResult(success=True, message_id=message.sid)
        except TwilioRestException as e:
            return SendResult(success=False, error=str(e))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        pass
