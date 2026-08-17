# Web Search Tool
**Version:** 2.0.0

Search the web by query or fetch a URL.

## Parameters
- `query` (string, required): Search query, or URL starting with http:// or https://
- `max_results` (int, optional, default=5): Max search results (1–10), or page chars limit for URL fetch
- `timeout` (int, optional, default=20): Timeout in seconds

## Returns
- Search: markdown bullet list `- [title](url)  snippet`
- URL fetch: page content with HTML/script/style stripped

## Behavior
- **SSRF guard**: URL fetch blocks loopback/private/link-local/reserved IPs and cloud-metadata hosts (fails closed on unresolved hostnames); opt in to private fetches with `NEXUS_WEB_FETCH_ALLOW_PRIVATE=1`
- **Dual backend**: Bing RSS primary, DuckDuckGo HTML fallback
- **Query rewriting**: `today` queries get a `latest` variant plus the current UTC date appended; `breaking` queries get `latest` appended
