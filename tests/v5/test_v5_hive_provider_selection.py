from nexus.main_agent.hive import V5Hive


class _Provider:
    def generate(self, **kwargs):
        assert kwargs["messages"][-1]["content"] == "subtask"
        return "local result"


class _Factory:
    def get_provider(self):
        return _Provider()


def test_hive_llm_uses_configured_factory_provider(monkeypatch):
    monkeypatch.setattr("models.providers.core.factory.NexusProviderFactory", lambda: _Factory())
    host = object.__new__(V5Hive)
    assert host._hive_llm_call()([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "subtask"},
    ]) == "local result"
