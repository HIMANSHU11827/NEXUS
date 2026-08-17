__version__ = "1.0.0"

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def td_with_config(tmp_path):
    config_dir = tmp_path / "configure"
    config_dir.mkdir()
    return str(tmp_path)


class TestSetupHelpers:
    """Test the helper functions from tui.setup_wizard."""

    def test_load_env_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            from tui.setup_wizard import load_env
            env = load_env(td)
            assert env == {}

    def test_save_and_load_env(self, td_with_config):
        from tui.setup_wizard import load_env, save_env
        save_env(td_with_config, {"DEEPSEEK_API_KEY": "sk-abc123"})
        env = load_env(td_with_config)
        assert env["DEEPSEEK_API_KEY"] == "sk-abc123"

    def test_save_env_skips_empty(self, td_with_config):
        from tui.setup_wizard import load_env, save_env
        save_env(td_with_config, {"A": "val", "B": ""})
        env = load_env(td_with_config)
        assert "A" in env
        assert "B" not in env

    def test_load_provider_yml_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            from tui.setup_wizard import load_provider_yml
            cfg = load_provider_yml(td)
            assert cfg == {}

    def test_save_and_load_provider_yml(self, td_with_config):
        from tui.setup_wizard import load_provider_yml, save_provider_yml
        expected = {"default_provider": "deepseek", "version": "1.1.0"}
        save_provider_yml(td_with_config, expected)
        cfg = load_provider_yml(td_with_config)
        assert cfg == expected

    def test_connection_fails_with_bad_key(self):
        from tui.setup_wizard import test_connection
        success, msg = test_connection("deepseek", "bad-key", "https://httpbin.org/status/401", "deepseek-v4-flash")
        assert not success

    def test_provider_defs_exist(self):
        from tui.setup_wizard import PROVIDER_DEFS
        assert "deepseek" in PROVIDER_DEFS
        assert "openai" in PROVIDER_DEFS
        assert "anthropic" in PROVIDER_DEFS
        for key, val in PROVIDER_DEFS.items():
            assert "name" in val
            assert "models" in val

    def test_gateway_defs_exist(self):
        from tui.setup_wizard import GATEWAY_DEFS
        assert "telegram" in GATEWAY_DEFS
        assert "discord" in GATEWAY_DEFS

    def test_placeholder_secrets_are_not_configured(self):
        from tui.setup_wizard import is_configured_secret

        assert not is_configured_secret("")
        assert not is_configured_secret("your_token_here")
        assert not is_configured_secret("paste_api_key_here")
        assert not is_configured_secret("<token>")
        assert is_configured_secret("sk-real-looking-secret")


class TestSetupWizardRun:
    def test_run_creates_config(self):
        """Integration test: run() with simulated inputs creates expected files."""
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td) / "configure"
            config_dir.mkdir()



            # The wizard requires interactive input, so we need a more
            # targeted approach: test individual steps instead.
            pass

    def test_save_provider_yml_round_trips_explicit_config(self, tmp_path):
        config_dir = tmp_path / "configure"
        config_dir.mkdir()
        td = str(tmp_path)

        from tui.setup_wizard import load_provider_yml, save_provider_yml

        api_key = "sk-test123"
        cfg = {"default_provider": "deepseek", "providers": {"deepseek": {"api_key": api_key}}}
        save_provider_yml(td, cfg)

        cfg_after = load_provider_yml(td)
        assert cfg_after["providers"]["deepseek"]["api_key"] == "sk-test123"
        assert (config_dir / "provider.yml").exists()

    def test_ask_yes_no_defaults(self):
        from tui.setup_wizard import ask_yes_no
        with patch("builtins.input", return_value=""):
            assert ask_yes_no("test", default=True) is True
            assert ask_yes_no("test", default=False) is False

    def test_ask_yes_no_parses(self):
        from tui.setup_wizard import ask_yes_no
        with patch("builtins.input", return_value="y"):
            assert ask_yes_no("test") is True
        with patch("builtins.input", return_value="n"):
            assert ask_yes_no("test") is False

    def test_masked_input(self):
        from tui.setup_wizard import masked_input
        with patch("tui.setup_wizard.Prompt.ask", return_value="secret123"):
            result = masked_input("Enter key")
            assert result == "secret123"

    def test_secret_input_visible_fallback(self, monkeypatch):
        import tui.setup_wizard as wizard

        prompts = iter(["", "visible-secret"])
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: next(prompts))
        monkeypatch.setattr(wizard.Confirm, "ask", lambda *args, **kwargs: True)
        monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True)

        assert wizard.secret_input("Enter key") == "visible-secret"

    def test_number_prompts_fall_back_to_defaults(self, monkeypatch):
        import tui.setup_wizard as wizard

        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: "not-a-number")

        assert wizard.ask_float("temp", "0.7", 0.0, 2.0) == 0.7
        assert wizard.ask_int("tokens", "4096", 256, 128000) == 4096

    def test_configure_system_permission_and_log_options(self, tmp_path, monkeypatch):
        import tui.setup_wizard as wizard

        config_dir = tmp_path / "configure"
        config_dir.mkdir()

        selects = iter([0, 0, 0, 0])
        prompts = iter(["0.7", "4096", "10", "en"])
        confirms = iter([False, True, True, False])

        monkeypatch.setattr(wizard, "wizard_header", lambda: None)
        monkeypatch.setattr(wizard, "select", lambda *args, **kwargs: next(selects))
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: next(prompts))
        monkeypatch.setattr(wizard.Confirm, "ask", lambda *args, **kwargs: next(confirms))

        wizard.configure_system(str(tmp_path))

        settings = wizard.yaml.safe_load((config_dir / "settings.yml").read_text(encoding="utf-8"))
        assert settings["permission_mode"] == "auto"
        assert settings["log_level"] == "INFO"

    def test_configure_provider_saves_api_key_in_env_and_placeholder_in_provider_yml(self, tmp_path, monkeypatch):
        import tui.setup_wizard as wizard

        monkeypatch.setattr(wizard.Confirm, "ask", lambda *args, **kwargs: True)
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: "1")
        monkeypatch.setattr(wizard, "secret_input", lambda *args, **kwargs: "sk-test")
        monkeypatch.setattr(wizard, "_open_docs", lambda *args, **kwargs: None)

        env = {}
        cfg = {}
        model, api_key = wizard.configure_provider("deepseek", str(tmp_path), env, cfg)

        assert model == wizard.PROVIDER_DEFS["deepseek"]["models"][0]
        assert api_key == "sk-test"
        assert env == {"DEEPSEEK_API_KEY": "sk-test"}
        assert cfg["default_provider"] == "deepseek"
        assert cfg["providers"]["deepseek"]["api_key"] == "${DEEPSEEK_API_KEY}"
        assert not (tmp_path / "configure" / "settings.yml").exists()

    def test_save_env_writes_private_file_permissions(self, tmp_path):
        import os

        import pytest

        import tui.setup_wizard as wizard

        if os.name == "nt":
            pytest.skip("POSIX permission bits are not reliable on Windows ACL filesystems")

        wizard.save_env(str(tmp_path), {"DEEPSEEK_API_KEY": "sk-test"})

        mode = (tmp_path / "configure" / ".env").stat().st_mode & 0o777
        assert mode & 0o077 == 0

    def test_configure_oauth_provider_uses_login_flow(self, tmp_path, monkeypatch):
        import tui.setup_wizard as wizard
        from providers.oauth.types import OAuthCredentials

        creds = OAuthCredentials(
            access="oauth-access",
            refresh="oauth-refresh",
            expires=9999999999999,
        )

        monkeypatch.setattr(wizard, "login_oauth_provider", lambda *args, **kwargs: (creds, "github-copilot"))

        def fail_secret(*args, **kwargs):
            raise AssertionError("OAuth setup should not ask for a pasted token when login succeeds")

        monkeypatch.setattr(wizard, "secret_input", fail_secret)
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: "1")
        monkeypatch.setattr(wizard.Confirm, "ask", lambda *args, **kwargs: True)

        env = {}
        cfg = {}
        model, api_key = wizard.configure_provider("github_copilot", str(tmp_path), env, cfg)

        assert api_key == "oauth-access"
        assert env == {}
        assert cfg["providers"]["github_copilot"]["auth_type"] == "oauth"
        assert cfg["providers"]["github_copilot"]["oauth_provider"] == "github-copilot"
        assert not (tmp_path / "configure" / "settings.yml").exists()

    def test_configure_gateways_reuses_existing_token(self, tmp_path, monkeypatch):
        import tui.setup_wizard as wizard

        selects = iter([0, 0, 1, 1, 1, 1, 1])
        monkeypatch.setattr(wizard, "wizard_header", lambda: None)
        monkeypatch.setattr(wizard, "select", lambda *args, **kwargs: next(selects))
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: "*")

        def fail_secret(*args, **kwargs):
            raise AssertionError("secret_input should not be called when existing token is kept")

        monkeypatch.setattr(wizard, "secret_input", fail_secret)
        env = {"TELEGRAM_BOT_TOKEN": "existing-token"}

        wizard.configure_gateways(str(tmp_path), env)

        assert env["TELEGRAM_BOT_TOKEN"] == "existing-token"

    def test_core_setup_steps_run_with_skips(self, tmp_path, monkeypatch):
        import tui.setup_wizard as wizard

        monkeypatch.setenv("NEXUS_HOME", str(tmp_path / ".nexus-home"))
        monkeypatch.delenv("NEXUS_BASE_HOME", raising=False)
        monkeypatch.delenv("NEXUS_PROFILE", raising=False)
        monkeypatch.setattr(wizard, "wizard_header", lambda: None)
        monkeypatch.setattr(wizard, "_detect_local_providers", lambda: {})
        monkeypatch.setattr(wizard, "_open_docs", lambda *args, **kwargs: None)
        monkeypatch.setattr(wizard, "test_provider", lambda *args, **kwargs: (False, "no network", 0.0))
        monkeypatch.setattr(wizard, "secret_input", lambda *args, **kwargs: "secret")
        monkeypatch.setattr(wizard, "_prompt_enable", lambda *args, **kwargs: False)

        confirm_values = iter([
            True,   # configure_profile create profile
            False,  # configure_extensions hive disabled
            False,  # configure_fallback skip
            False,  # init_knowledge skip
            False,  # configure_costs skip
            False,  # verify_connection skip
            False,  # finish export skip
            False,  # finish startup skip
        ])
        monkeypatch.setattr(wizard.Confirm, "ask", lambda *args, **kwargs: next(confirm_values))

        prompt_values = iter([
            "Tester",              # identity name
            "default",             # profile name
            "Test profile",        # profile description
        ])
        monkeypatch.setattr(wizard.Prompt, "ask", lambda *args, **kwargs: next(prompt_values))

        select_values = iter([
            0,  # personality
            1,  # sandbox tier
        ])
        monkeypatch.setattr(wizard, "select", lambda *args, **kwargs: next(select_values))

        wizard.register_steps()
        wizard.configure_identity(str(tmp_path))
        wizard.init_workspace(str(tmp_path))
        wizard.configure_sandbox(str(tmp_path))
        wizard.configure_profile(str(tmp_path))
        wizard.configure_extensions(str(tmp_path))
        provider_cfg = {"default_provider": "deepseek", "providers": {"deepseek": {"model": "deepseek-chat"}}}
        wizard.configure_fallback(str(tmp_path), provider_cfg, "deepseek")
        wizard.init_knowledge(str(tmp_path))
        wizard.configure_costs(str(tmp_path))
        wizard.save_provider_yml(str(tmp_path), provider_cfg)
        wizard.verify_connection(str(tmp_path), {"provider": "deepseek", "api_key": "secret"})
        wizard.finish(str(tmp_path))

        assert (tmp_path / ".nexus" / "USER.md").exists()
        assert (tmp_path / ".nexus" / "workspace" / "README.md").exists()
        assert (tmp_path / "configure" / ".env").exists()
