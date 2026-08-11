"""Security tests: secrets must never leak through the ``system env`` tool."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.system.scripts.system import SystemTool


def _run(coro):
    return asyncio.run(coro)


class TestSystemEnvRedaction:
    def test_audit_has_an_explicit_entry_budget(self, tmp_path):
        for index in range(5):
            (tmp_path / f"file-{index}.txt").write_text("x", encoding="utf-8")

        result = _run(SystemTool(root_dir=str(tmp_path)).execute(
            action="audit", max_entries=3
        ))

        assert result.success is True
        assert "limited to 3" in result.output
        assert "Audit: 3 entries found" in result.output

    def test_system_diagnostics_do_not_block_event_loop(self, tmp_path, monkeypatch):
        tool = SystemTool(root_dir=str(tmp_path))
        original = tool._execute_sync

        def slow_diagnostics(*args, **kwargs):
            import time

            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(tool, "_execute_sync", slow_diagnostics)

        async def run_with_heartbeat():
            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                result = await tool.execute(action="info")
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            return result, ticks

        result, ticks = _run(run_with_heartbeat())
        assert result.success is True
        assert ticks >= 4

    def test_env_redacts_api_keys_and_tokens(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real_value_123456789")
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza_fake_metadata_value")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token_value_123")
        monkeypatch.setenv("NEXUS_PROVIDER", "openai")
        monkeypatch.setenv("NEXUS_MODEL", "gpt-4o")

        result = _run(SystemTool().execute(action="env"))
        assert result.success is True

        output = result.output
        assert "DEEPSEEK_API_KEY=**<redacted>**" in output
        assert "GOOGLE_API_KEY=**<redacted>**" in output
        assert "GITHUB_TOKEN=**<redacted>**" in output
        # The actual secret values must not appear anywhere in the output.
        assert "sk-real_value_123456789" not in output
        assert "AIza_fake_metadata_value" not in output
        assert "ghp_fake_token_value_123" not in output
        # Legitimate, non-secret variables keep their values.
        assert "NEXUS_PROVIDER=openai" in output
        assert "NEXUS_MODEL=gpt-4o" in output

    def test_env_redacts_oauth_and_password_vars(self, monkeypatch):
        monkeypatch.setenv("CLIENT_SECRET", "s3cret_value")
        monkeypatch.setenv("SMTP_PASSWORD", "mail-pass")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE00000000")

        output = _run(SystemTool().execute(action="env")).output
        assert "CLIENT_SECRET=**<redacted>**" in output
        assert "SMTP_PASSWORD=**<redacted>**" in output
        assert "AWS_ACCESS_KEY_ID=**<redacted>**" in output
        assert "s3cret_value" not in output
        assert "mail-pass" not in output
        assert "AKIAFAKE00000000" not in output

    def test_env_still_lists_non_secret_variables(self, monkeypatch):
        monkeypatch.setenv("NEXUS_PROVIDER", "lm_studio")
        monkeypatch.setenv("MY_TOOL_PATH", "/tools")
        output = _run(SystemTool().execute(action="env")).output
        assert "MY_TOOL_PATH=/tools" in output

    def test_unrelated_actions_unaffected(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-topsecret_981655")
        info = _run(SystemTool().execute(action="info"))
        assert info.success is True
        assert "sk-topsecret_981655" not in info.output

    def test_redact_helper_matches_name_not_value(self):
        # "PATH" must NOT be redacted; "APIKEY" must be.
        assert SystemTool._redact_env("PATH", "/usr/bin") == "/usr/bin"
        assert SystemTool._redact_env("OPENAI_API_KEY", "x") == "**<redacted>**"
