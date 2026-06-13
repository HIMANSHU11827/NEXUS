import unittest
from unittest.mock import Mock, patch


class TestOpenRouterProvider(unittest.TestCase):
    def _make_provider(self, api_key="test-key", model=""):
        from providers.base import NexusBaseProvider
        from providers.openrouter import OpenRouterProvider

        def fake_base_init(instance, provider_name, endpoint):
            instance.provider_name = provider_name
            instance.endpoint = endpoint
            instance.model = model
            instance.api_key = api_key
            instance.headers = {}
            instance.session = Mock()

        with patch.object(NexusBaseProvider, "__init__", fake_base_init):
            return OpenRouterProvider()

    def test_defaults_to_documented_free_router(self):
        provider = self._make_provider()
        self.assertEqual(provider.model, "openrouter/free")

    def test_missing_key_does_not_call_network(self):
        provider = self._make_provider(api_key="")
        result = provider.generate(prompt="hi")
        self.assertIn("OpenRouter API key is missing", result)
        provider.session.post.assert_not_called()

    def test_missing_key_stream_does_not_call_network(self):
        provider = self._make_provider(api_key="")
        chunks = list(provider.stream_generate(prompt="hi"))
        self.assertEqual(len(chunks), 1)
        self.assertIn("OpenRouter API key is missing", chunks[0])
        provider.session.post.assert_not_called()

    def test_generate_uses_free_router_payload(self):
        provider = self._make_provider()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        provider.session.post.return_value = response

        self.assertEqual(provider.generate(prompt="hi"), "ok")
        payload = provider.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "openrouter/free")


if __name__ == "__main__":
    unittest.main()
