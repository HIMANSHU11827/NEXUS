import importlib
import asyncio

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult
from gateway.run import GatewayRunner
from gateway.session_bus_integration import GatewaySessionManager


class FakeAdapter(BasePlatformAdapter):
    def __init__(self, platform: str):
        super().__init__(platform)
        self.sent: list[str] = []
        self.typing_sent = False

    async def connect(self) -> bool:
        return True

    async def disconnect(self):
        return None

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> SendResult:
        self.sent.append(text)
        return SendResult(success=True)

    async def send_typing(self, chat_id: str):
        self.typing_sent = True


def test_gateway_main_exports_run():
    module = importlib.import_module("gateway.main")

    assert callable(module.run)


def test_gateway_adapter_factory_loads_only_requested_optional_module(monkeypatch):
    import gateway.platforms as platforms

    imported = []
    real_import = platforms.import_module

    def tracked_import(name):
        imported.append(name)
        if name == "gateway.platforms.slack":
            raise RuntimeError("slack should stay lazy")
        return real_import(name)

    monkeypatch.setattr(platforms, "import_module", tracked_import)

    adapter = platforms.get_adapter("telegram")

    assert adapter.platform == "telegram"
    assert imported == ["gateway.platforms.telegram"]


def test_register_all_uses_setup_wizard_gateway_env_names(monkeypatch):
    import gateway.run as gateway_run

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-token")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)

    monkeypatch.setattr(gateway_run, "all_adapters", lambda: ["telegram", "discord", "slack"])
    monkeypatch.setattr(gateway_run, "get_adapter", lambda platform: FakeAdapter(platform))

    runner = GatewayRunner()
    runner.register_all()

    assert sorted(runner.adapters) == ["discord", "telegram"]


def test_gateway_runner_and_session_manager_share_session_ids(tmp_path):
    event = MessageEvent(text="hi", sender_id="user", chat_id="chat/with spaces", platform="telegram")
    manager = GatewaySessionManager(str(tmp_path))

    assert GatewayRunner.session_id_for(event) == manager.resolve_session("telegram", "chat/with spaces")


def test_canonical_adapters_accept_env_aliases(monkeypatch):
    from gateway.platforms.discord import DiscordAdapter
    from gateway.platforms.telegram import TelegramAdapter
    from gateway.platforms.whatsapp import WhatsAppAdapter

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-token")
    monkeypatch.setenv("META_ACCESS_TOKEN", "meta-token")

    assert TelegramAdapter().token == "telegram-token"
    assert DiscordAdapter().token == "discord-token"
    assert WhatsAppAdapter().access_token == "meta-token"


def test_gateway_handle_message_consumes_content_chunks(monkeypatch):
    import gateway.run as gateway_run

    class FakeLoop:
        root = "C:\\project"

        def load_memory(self, session_id):
            self.session_id = session_id

        async def stream_run(self, text):
            yield {"type": "status", "data": "Starting"}
            yield {"type": "content", "data": "hello "}
            yield {"type": "tools_discovered", "data": ["reading"]}
            yield {"type": "content", "data": "world"}

    monkeypatch.setattr(gateway_run, "NexusLoop", FakeLoop)
    monkeypatch.setattr(gateway_run, "set_active_session_id", lambda *_args, **_kwargs: None, raising=False)

    from utils import session_bus
    monkeypatch.setattr(session_bus, "set_active_session_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_bus, "sync_loop_from_disk", lambda _loop: None)
    monkeypatch.setattr("authentication.is_gateway_authorized", lambda _platform, _sender: True)

    runner = GatewayRunner()
    adapter = FakeAdapter("telegram")
    runner.add_adapter(adapter)

    event = MessageEvent(text="hi", sender_id="user", chat_id="chat", platform="telegram")
    asyncio.run(runner.handle_message(event))

    assert adapter.typing_sent is True
    assert adapter.sent == ["hello world"]


def test_gateway_handle_message_retains_legacy_string_chunk_support(monkeypatch):
    import gateway.run as gateway_run

    class FakeLoop:
        root = "C:\\project"

        def load_memory(self, session_id):
            self.session_id = session_id

        async def stream_run(self, text):
            yield "[NEXUS_ACTIVITY] hidden"
            yield "legacy "
            yield "response"

    monkeypatch.setattr(gateway_run, "NexusLoop", FakeLoop)

    from utils import session_bus
    monkeypatch.setattr(session_bus, "set_active_session_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_bus, "sync_loop_from_disk", lambda _loop: None)
    monkeypatch.setattr("authentication.is_gateway_authorized", lambda _platform, _sender: True)

    runner = GatewayRunner()
    adapter = FakeAdapter("telegram")
    runner.add_adapter(adapter)

    event = MessageEvent(text="hi", sender_id="user", chat_id="chat", platform="telegram")
    asyncio.run(runner.handle_message(event))

    assert adapter.sent == ["legacy response"]
