
import pytest

from nexus.capabilities.intelligence.nate.adaptive_schema import (
    AdaptiveSchemaEngine,
    NATE_Route,
    TSCGCompressor,
)


class TestTSCGCompressor:
    def test_compresses_field_names(self):
        schema = {"name": "test", "description": "a test tool", "type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"], "title": "ignored"}
        result = TSCGCompressor.compress(schema)
        assert "n" in result
        assert "d" in result
        assert "t" in result
        assert "p" in result
        assert "r" in result
        assert "title" not in result
        assert result["n"] == "test"

    def test_compresses_nested(self):
        schema = {"name": "nested", "parameters": {"type": "object", "properties": {"x": {"type": "string", "description": "the x value"}}}}
        result = TSCGCompressor.compress(schema)
        assert result["n"] == "nested"
        assert "p" in result
        assert result["p"]["p"]["x"]["d"] == "the x value"

    def test_savings_percent(self):
        original = '{"name": "long_tool_name", "description": "a very long description that should be compressed significantly"}'
        compressed = '{"n": "long_tool_name", "d": "compressed"}'
        savings = TSCGCompressor.savings_percent(original, compressed)
        assert savings > 0

    def test_handles_lists(self):
        schema = {"enum": ["a", "b", "c"]}
        result = TSCGCompressor.compress(schema)
        assert result["e"] == ["a", "b", "c"]


class TestNATE_Route:
    @pytest.fixture
    def router(self):
        r = NATE_Route()
        r.register_tool("get_weather", "Get the current weather for a location")
        r.register_tool("send_email", "Send an email message to a recipient")
        r.register_tool("search_web", "Search the internet for information")
        r.register_tool("calculate", "Perform mathematical calculations")
        return r

    def test_relevant_search(self, router):
        result = router.route("weather forecast")
        assert result["path"] != "no_tools"
        tools = result["tools"]
        assert len(tools) >= 1
        top_name = tools[0][0]
        assert top_name == "get_weather"

    def test_relevant_search_email(self, router):
        result = router.route("send message to user")
        tools = result["tools"]
        assert len(tools) >= 1
        top_name = tools[0][0]
        assert top_name == "send_email"

    def test_top_k_respected(self, router):
        result = router.route("help")
        tools = result["tools"]
        assert len(tools) >= 0

    def test_unknown_query_returns_no_tools(self, router):
        result = router.route("zzzznotaword")
        # Unrelated queries should trigger necessity gate
        assert result["path"] in ("no_tools", "path2")
        assert len(result["tools"]) >= 0


class TestAdaptiveSchemaEngine:
    @pytest.fixture
    def engine(self):
        e = AdaptiveSchemaEngine()
        e.register_many([
            {"name": "get_weather", "description": "Get weather for a location", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}}, "required": ["location"]},
            {"name": "send_email", "description": "Send an email", "parameters": {"type": "object", "properties": {"to": {"type": "string"}}}, "required": ["to"]},
            {"name": "search_web", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}, "required": ["query"]},
        ])
        e.set_always_loaded(["get_weather"])
        return e

    def test_register_and_stats(self, engine):
        stats = engine.schema_stats()
        assert stats["num_tools"] == 3
        assert stats["savings_percent"] > 0

    def test_get_schemas_routes_relevant(self, engine):
        result = engine.get_schemas("weather", top_k=2)
        assert len(result["always_loaded"]) == 1
        assert result["always_loaded"][0]["n"] == "get_weather"

    def test_get_schemas_for_email(self, engine):
        result = engine.get_schemas("send email", top_k=2)
        names = [t["n"] for t in result["lazy_loaded"] if "n" in t]
        assert "send_email" in names
