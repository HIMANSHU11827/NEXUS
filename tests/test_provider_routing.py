import os
import tempfile
import unittest
from unittest.mock import patch


class TestConfigSecretPlaceholders(unittest.TestCase):
    def test_env_placeholders_are_expanded_without_committed_secrets(self):
        from core.config_loader import NexusConfigLoader

        NexusConfigLoader._reset_instance()
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".yaml") as f:
            f.write(
                "providers:\n"
                "  cloud:\n"
                "    openrouter:\n"
                "      active: true\n"
                "      api_key: ${OPENROUTER_API_KEY}\n"
                "      model: test\n"
                "system:\n"
                "  log_level: INFO\n"
                "security:\n"
                "  safety_strictness: 0.8\n"
            )
            path = f.name
        try:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-secret"}, clear=False):
                loader = NexusConfigLoader(path)
                self.assertEqual(loader.get_provider_config("openrouter")["api_key"], "env-secret")
        finally:
            NexusConfigLoader._reset_instance()
            os.remove(path)

    def test_provider_env_override_preserves_api_key_setting_name(self):
        from core.config_loader import NexusConfigLoader

        NexusConfigLoader._reset_instance()
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".yaml") as f:
            f.write(
                "providers:\n"
                "  cloud:\n"
                "    openrouter:\n"
                "      active: true\n"
                "      api_key: old\n"
                "      model: old-model\n"
                "system:\n"
                "  log_level: INFO\n"
                "security:\n"
                "  safety_strictness: 0.8\n"
            )
            path = f.name
        try:
            with patch.dict(os.environ, {"NEXUS_PROVIDERS_CLOUD_OPENROUTER_API_KEY": "new-secret"}, clear=False):
                loader = NexusConfigLoader(path)
                config = loader.get_provider_config("openrouter")
                self.assertEqual(config["api_key"], "new-secret")
                self.assertNotIn("openrouter_api", loader.get("providers.cloud", {}))
        finally:
            NexusConfigLoader._reset_instance()
            os.remove(path)

    def test_active_providers_exclude_missing_cloud_credentials(self):
        from core.config_loader import NexusConfigLoader

        NexusConfigLoader._reset_instance()
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".yaml") as f:
            f.write(
                "providers:\n"
                "  cloud:\n"
                "    openrouter:\n"
                "      active: true\n"
                "      api_key: YOUR_OPENROUTER_API_KEY\n"
                "    groq:\n"
                "      active: true\n"
                "      api_key: live-key\n"
                "  local:\n"
                "    ollama:\n"
                "      active: true\n"
            )
            path = f.name
        try:
            loader = NexusConfigLoader(path)
            active = loader.get_active_providers()
            self.assertNotIn("openrouter", active)
            self.assertIn("groq", active)
            self.assertIn("ollama", active)
        finally:
            NexusConfigLoader._reset_instance()
            os.remove(path)

    def test_config_save_creates_parent_directory(self):
        from core.config_loader import NexusConfigLoader

        NexusConfigLoader._reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "nexus_config.yaml")
            loader = NexusConfigLoader(path)
            loader.data = {"system": {"log_level": "INFO"}}
            self.assertTrue(loader.save())
            self.assertTrue(os.path.exists(path))
        NexusConfigLoader._reset_instance()


class TestProviderCapabilityRouting(unittest.TestCase):
    def test_choose_skips_degraded_and_prefers_context_strength(self):
        from core.providers.health import ProviderCapabilityRegistry, ProviderHealthRegistry

        health = ProviderHealthRegistry()
        health.mark_failure("gemini", "timeout")
        selected = ProviderCapabilityRegistry().choose(["ollama", "gemini", "openai"], health)
        self.assertEqual(selected[0], "openai")
        self.assertNotIn("gemini", selected)

    def test_vision_requests_filter_to_vision_capable_providers(self):
        from core.providers.health import ProviderCapabilityRegistry, ProviderHealthRegistry

        selected = ProviderCapabilityRegistry().choose(["ollama", "groq", "gemini"], ProviderHealthRegistry(), vision=True)
        self.assertEqual(selected, ["gemini"])

    def test_router_fallback_treats_error_strings_as_failures(self):
        from core.providers.health import ProviderHealthRegistry
        from core.providers.router import ModelRouter

        class FakeProvider:
            def __init__(self, value):
                self.value = value

            def validate_api_key(self):
                return True

            def generate(self, **kwargs):
                return self.value

        class FakeFactory:
            def get_provider_by_id(self, provider_id):
                return FakeProvider("Error: local model missing" if provider_id == "bad" else "ok")

        router = object.__new__(ModelRouter)
        router.factory = FakeFactory()
        router.health = ProviderHealthRegistry()

        result = router._generate_with_fallbacks([{"role": "user", "content": "hi"}], ["bad", "good"])
        self.assertEqual(result, "ok")
        self.assertFalse(router.health.get("bad").healthy)
        self.assertTrue(router.health.get("good").healthy)


if __name__ == "__main__":
    unittest.main()
