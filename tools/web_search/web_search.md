# Web Search Tool
**Version:** 1.2.0

Search the web by query or fetch a URL.

## Parameters
- `query` (string, required): Search query, or URL starting with http:// or https://
- `max_results` (int, optional, default=5): Max search results, or page chars limit for URL fetch
- `timeout` (int, optional, default=20): Timeout in seconds

## Returns
- Search: numbered results with title, URL, snippet
- URL fetch: page content with HTML/script/style stripped
