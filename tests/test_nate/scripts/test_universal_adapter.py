import pytest

from intelligence.nate.universal_adapter import UniversalAdapter, UniversalTool


@pytest.fixture
def sample_tools():
    return [
        UniversalTool("get_weather", "Get weather for a location", {"type": "object", "properties": {"location": {"type": "string"}}}, ["location"]),
        UniversalTool("send_email", "Send an email", {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}}}, ["to", "subject"]),
        UniversalTool("search_web", "Search the web", {"type": "object", "properties": {"query": {"type": "string"}}}, ["query"]),
    ]


class TestUniversalAdapter:
    def test_register_and_get(self):
        adapter = UniversalAdapter()
        tool = UniversalTool("test", "test tool", {"type": "object", "properties": {"x": {"type": "string"}}}, ["x"])
        adapter.register(tool)
        assert adapter.get("test") is tool
        assert adapter.get("nonexistent") is None

    def test_register_many(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        assert len(adapter.all()) == 3

    def test_convert_openai(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        result = adapter.convert("openai")
        assert len(result) == 3
        for r in result:
            assert r["type"] == "function"
            assert "function" in r
            assert "name" in r["function"]
            assert "parameters" in r["function"]

    def test_convert_anthropic(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        result = adapter.convert("anthropic")
        assert len(result) == 3
        for r in result:
            assert "name" in r
            assert "input_schema" in r

    def test_convert_google(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        result = adapter.convert("google")
        assert len(result) == 3
        for r in result:
            assert "name" in r
            assert "parameters" in r

    def test_selective_convert(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        result = adapter.convert("openai", names=["get_weather"])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "get_weather"

    def test_from_dict_roundtrip(self):
        data = {"name": "roundtrip", "description": "test", "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}, "required": ["x"]}
        tool = UniversalTool.from_dict(data)
        assert tool.name == "roundtrip"
        assert tool.description == "test"
        assert tool.required == ["x"]
        back = tool.to_dict()
        assert back["name"] == "roundtrip"

    def test_token_counting(self, sample_tools):
        adapter = UniversalAdapter()
        adapter.register_many(sample_tools)
        before = adapter.count_tokens_before()
        after = adapter.count_tokens_after_triple()
        assert before > after
        assert adapter.count_tokens_before(names=["get_weather"]) < before
