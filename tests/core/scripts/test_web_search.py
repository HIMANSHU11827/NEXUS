from extensions.tools.built_in.web_search.scripts.web_search import _DuckDuckGoResultsParser
from extensions.tools.built_in.web_search.scripts.web_search import WebSearchTool


def test_web_search_retries_today_query_with_latest_variants(monkeypatch):
    calls = []

    def fake_search(query, limit):
        calls.append(query)
        if query.endswith("latest"):
            return [{"title": "Latest", "url": "https://example.com", "snippet": "ok"}]
        return []

    monkeypatch.setattr(WebSearchTool, "_search", staticmethod(fake_search))

    import asyncio
    result = asyncio.run(WebSearchTool().execute(query="breaking news today"))

    assert result.success is True
    assert calls[:2] == ["breaking news today", "breaking news latest"]
    assert "Latest" in result.output


def test_duckduckgo_parser_captures_real_source_metadata():
    parser = _DuckDuckGoResultsParser()
    parser.feed(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">Example Doc</a>'
        '<a class="result__snippet">Primary source summary</a>'
    )

    assert parser.results == [{
        "title": "Example Doc",
        "url": "https://example.com/doc",
        "snippet": "Primary source summary",
    }]
