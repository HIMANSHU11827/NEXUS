from tools.web_search.scripts.web_search import _DuckDuckGoResultsParser


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
