# Live News Tool

Fetch real-time news when the user asks for "today's news" to avoid stale results.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/live_news_tool.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
When the user asks for "today's news", NEXUS risks returning stale or outdated information. This tool would fetch real-time news from live sources so answers reflect current events rather than cached knowledge.

## Notes
Overlaps with `web_search` (live web results) and `news_aggregator_live` (multi-source aggregation); both can partially serve this need today.
