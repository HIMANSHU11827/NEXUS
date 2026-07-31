"""
Tests for the Signal, Matrix, and Mattermost gateway adapters.

These tests are *env-gated* and *network-free*: they never require a live
Signal/Matrix/Mattermost server, and they must pass whether or not the
optional ``matrix-nio`` / ``websockets`` dependencies are installed.
The optional deps are exercised through lightweight fakes injected in place of
the real HTTP/Matrix clients.
"""

import asyncio
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

# Ensure the project root is importable regardless of pytest's rootdir discovery.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.base import SendResult  # noqa: E402
from gateway.platforms.signal import SignalAdapter  # noqa: E402
from gateway.platforms.matrix import MatrixAdapter, HAS_MATRIX_NIO  # noqa: E402
from gateway.platforms.mattermost import MattermostAdapter, HAS_WEBSOCKETS  # noqa: E402


# ---------------------------------------------------------------------------
# Lightweight fakes for the network clients
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, json_data=None, is_success=True, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.is_success = is_success
        self.status_code = status_code

    def json(self):
        return self._json


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used by Signal / Mattermost."""

    def __init__(self, response=None):
        self.response = response or FakeResponse({"timestamp": 12345, "id": "post1"})
        self.calls = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.response

    async def aclose(self):
        self.closed = True


class FakeMatrixClient:
    """Stand-in for nio.AsyncClient used by the Matrix adapter."""

    def __init__(self):
        self.sent = []

    async def room_send(self, room_id, message_type, content):
        self.sent.append((room_id, message_type, content))
        return SimpleNamespace(event_id="$evt_sent")


def make_handler(events):
    async def _handler(event):
        events.append(event)
    return _handler


# ---------------------------------------------------------------------------
# Signal adapter
# ---------------------------------------------------------------------------
def test_signal_name():
    assert SignalAdapter.name == "signal"
    assert SignalAdapter().platform == "signal"


def test_signal_env_gating_missing_number(monkeypatch):
    monkeypatch.delenv("SIGNAL_NUMBER", raising=False)
    monkeypatch.delenv("SIGNAL_RPC_URL", raising=False)
    adapter = SignalAdapter()
    assert adapter.number == ""
    # Without a configured number, connect() must refuse.
    assert asyncio.run(adapter.connect()) is False


def test_signal_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("SIGNAL_NUMBER", "+15551234567")
    monkeypatch.setenv("SIGNAL_RPC_URL", "http://signal-cli:8080")
    adapter = SignalAdapter()
    assert adapter.number == "+15551234567"
    assert adapter.rpc_url == "http://signal-cli:8080"


async def test_signal_process_incoming_data_message():
    adapter = SignalAdapter(number="+15550001111")
    events = []
    adapter.set_message_handler(make_handler(events))

    await adapter._process_incoming({
        "envelope": {
            "source": "+15550001111",
            "dataMessage": {"message": "hello world", "timestamp": 1700000000000},
        }
    })

    assert len(events) == 1
    ev = events[0]
    assert ev.text == "hello world"
    assert ev.sender_id == "+15550001111"
    assert ev.chat_id == "+15550001111"
    assert ev.platform == "signal"
    assert ev.message_id == "1700000000000"


async def test_signal_process_incoming_sync_message():
    adapter = SignalAdapter(number="+15550001111")
    events = []
    adapter.set_message_handler(make_handler(events))

    await adapter._process_incoming({
        "envelope": {
            "syncMessage": {
                "sent": {
                    "destination": "+15552223333",
                    "message": "synced hi",
                    "timestamp": 42,
                }
            }
        }
    })

    assert len(events) == 1
    ev = events[0]
    assert ev.text == "synced hi"
    assert ev.sender_id == "+15552223333"
    assert ev.message_id == "42"


async def test_signal_send_text_not_connected():
    adapter = SignalAdapter(number="+15550001111")
    result = await adapter.send_text("chat", "hi")
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


async def test_signal_send_text_success_and_reply():
    adapter = SignalAdapter(number="+15550001111")
    fake = FakeAsyncClient(response=FakeResponse({"timestamp": 999}))
    adapter._client = fake

    result = await adapter.send_text("+15559998888", "ping", reply_to="123")
    assert result.success is True
    assert result.message_id == "999"

    # The reply_to must be translated into a quote payload.
    assert fake.calls, "expected a POST to the send endpoint"
    _, url, kwargs = fake.calls[0]
    assert url == "/v2/send"
    assert kwargs["json"]["recipients"] == ["+15559998888"]
    assert kwargs["json"]["message"] == "ping"
    assert kwargs["json"]["quote"] == {"timestamp": 123, "author": "+15559998888"}


# ---------------------------------------------------------------------------
# Matrix adapter
# ---------------------------------------------------------------------------
def test_matrix_name():
    assert MatrixAdapter.name == "matrix"
    assert MatrixAdapter().platform == "matrix"


def test_matrix_module_imports_without_nio():
    # The whole point: the module must import even when matrix-nio is missing.
    import importlib
    import gateway.platforms.matrix as m
    importlib.reload(m)
    assert m.MatrixAdapter is not None


def test_matrix_env_gating_missing_config(monkeypatch):
    monkeypatch.delenv("MATRIX_HOMESERVER", raising=False)
    monkeypatch.delenv("MATRIX_USER", raising=False)
    monkeypatch.delenv("MATRIX_PASSWORD", raising=False)
    monkeypatch.delenv("MATRIX_ACCESS_TOKEN", raising=False)
    adapter = MatrixAdapter()
    # Either nio is missing, or the required homeserver/user pair is absent.
    assert asyncio.run(adapter.connect()) is False


def test_matrix_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://matrix.example.org")
    monkeypatch.setenv("MATRIX_USER", "@nexus:example.org")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "s3cr3t")
    adapter = MatrixAdapter()
    assert adapter.homeserver == "https://matrix.example.org"
    assert adapter.user == "@nexus:example.org"
    assert adapter.access_token == "s3cr3t"


class _FakeRoomMessage:
    def __init__(self, sender, body, event_id):
        self.sender = sender
        self.body = body
        self.event_id = event_id


async def test_matrix_on_room_message_forwards_and_ignores_self():
    adapter = MatrixAdapter(user="@nexus:example.org")
    events = []
    adapter.set_message_handler(make_handler(events))

    # Message from another user -> forwarded.
    await adapter._on_room_message("!room:example.org", _FakeRoomMessage(
        sender="@other:example.org", body="hi there", event_id="$evt1"))
    assert len(events) == 1
    ev = events[0]
    assert ev.text == "hi there"
    assert ev.sender_id == "@other:example.org"
    assert ev.chat_id == "!room:example.org"
    assert ev.platform == "matrix"
    assert ev.message_id == "$evt1"

    # Message from ourselves -> ignored.
    await adapter._on_room_message("!room:example.org", _FakeRoomMessage(
        sender="@nexus:example.org", body="echo", event_id="$evt2"))
    assert len(events) == 1


async def test_matrix_send_text_not_connected():
    adapter = MatrixAdapter(user="@nexus:example.org")
    result = await adapter.send_text("!room:example.org", "hi")
    assert result.success is False
    assert result.error == "Not connected"


async def test_matrix_send_text_success_and_reply():
    adapter = MatrixAdapter(user="@nexus:example.org")
    adapter._client = FakeMatrixClient()

    result = await adapter.send_text("!room:example.org", "pong", reply_to="$parent")
    assert result.success is True
    assert result.message_id == "$evt_sent"

    assert adapter._client.sent, "room_send should have been called"
    room_id, message_type, content = adapter._client.sent[0]
    assert room_id == "!room:example.org"
    assert message_type == "m.room.message"
    assert content["body"] == "pong"
    assert content["m.relates_to"] == {"m.in_reply_to": {"event_id": "$parent"}}


# ---------------------------------------------------------------------------
# Mattermost adapter
# ---------------------------------------------------------------------------
def test_mattermost_name():
    assert MattermostAdapter.name == "mattermost"
    assert MattermostAdapter().platform == "mattermost"


def test_mattermost_env_gating_missing_config(monkeypatch):
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_TEAM", raising=False)
    adapter = MattermostAdapter()
    assert asyncio.run(adapter.connect()) is False


def test_mattermost_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.org")
    monkeypatch.setenv("MATTERMOST_TOKEN", "tok123")
    monkeypatch.setenv("MATTERMOST_TEAM", "engineering")
    adapter = MattermostAdapter()
    assert adapter.url == "https://mm.example.org"
    assert adapter.token == "tok123"
    assert adapter.team == "engineering"


async def test_mattermost_handle_post_forwards_and_ignores_self():
    adapter = MattermostAdapter(url="https://mm.example.org", token="tok", team="eng")
    adapter._user_id = "u_self"
    events = []
    adapter.set_message_handler(make_handler(events))

    post = {
        "user_id": "u_other",
        "message": "team ping",
        "channel_id": "chan1",
        "id": "post_1",
    }
    await adapter._handle_post(json.dumps(post))
    assert len(events) == 1
    ev = events[0]
    assert ev.text == "team ping"
    assert ev.sender_id == "u_other"
    assert ev.chat_id == "chan1"
    assert ev.platform == "mattermost"
    assert ev.message_id == "post_1"

    # Our own post -> ignored.
    await adapter._handle_post(json.dumps({**post, "user_id": "u_self"}))
    assert len(events) == 1


async def test_mattermost_send_text_not_connected():
    adapter = MattermostAdapter(url="https://mm.example.org", token="tok")
    result = await adapter.send_text("chan1", "hi")
    assert result.success is False
    assert result.error == "Not connected"


async def test_mattermost_send_text_success_and_reply():
    adapter = MattermostAdapter(url="https://mm.example.org", token="tok")
    adapter._client = FakeAsyncClient(response=FakeResponse({"id": "post_99"}))
    adapter._user_id = "u_self"

    result = await adapter.send_text("chan1", "reply", reply_to="root_1")
    assert result.success is True
    assert result.message_id == "post_99"

    assert adapter._client.calls, "expected a POST to /posts"
    _, url, kwargs = adapter._client.calls[0]
    assert url == "/posts"
    assert kwargs["json"]["channel_id"] == "chan1"
    assert kwargs["json"]["message"] == "reply"
    assert kwargs["json"]["root_id"] == "root_1"


# ---------------------------------------------------------------------------
# Runner-level env-gating
# ---------------------------------------------------------------------------
def test_platform_env_map_covers_three_adapters():
    from gateway.run import _PLATFORM_ENV_MAP, _has_required_env

    assert _PLATFORM_ENV_MAP["signal"] == [["SIGNAL_NUMBER"]]
    assert _PLATFORM_ENV_MAP["matrix"] == [["MATRIX_HOMESERVER"], ["MATRIX_USER"]]
    assert _PLATFORM_ENV_MAP["mattermost"] == [["MATTERMOST_URL"], ["MATTERMOST_TOKEN"]]


def test_has_required_env_logic():
    from gateway.run import _has_required_env

    assert _has_required_env([["SIGNAL_NUMBER"]]) is False
    assert _has_required_env([["MATRIX_HOMESERVER"], ["MATRIX_USER"]]) is False


def test_register_all_skips_unconfigured_adapters(monkeypatch):
    for var in (
        "SIGNAL_NUMBER", "MATRIX_HOMESERVER", "MATRIX_USER",
        "MATRIX_ACCESS_TOKEN", "MATRIX_PASSWORD",
        "MATTERMOST_URL", "MATTERMOST_TOKEN",
        "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "META_ACCESS_TOKEN",
        "WHATSAPP_TOKEN", "SLACK_BOT_TOKEN", "SMTP_HOST", "TWILIO_ACCOUNT_SID",
    ):
        monkeypatch.delenv(var, raising=False)

    from gateway.run import GatewayRunner
    runner = GatewayRunner()
    runner.register_all()
    # None of the three target adapters should be active without env config.
    assert runner.adapters.get("signal") is None
    assert runner.adapters.get("matrix") is None
    assert runner.adapters.get("mattermost") is None


def test_optional_deps_flag_reported():
    # Documents the environment the tests ran under (not a hard requirement).
    assert isinstance(HAS_MATRIX_NIO, bool)
    assert isinstance(HAS_WEBSOCKETS, bool)
