from __future__ import annotations

__version__ = "1.2.0"
import asyncio
import html
import logging
import re
from html.parser import HTMLParser
from urllib import error as urlerror
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
try:
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:
    from xml.etree.ElementTree import fromstring as _xml_fromstring

from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("nexus.tools.web_search")


class _DuckDuckGoResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._capture = ""
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._capture = "title"
            self._href = values.get("href", "")
            self._text = []
        elif tag in {"a", "div"} and "result__snippet" in classes:
            self._capture = "snippet"
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            title = " ".join("".join(self._text).split())
            url = self._decode_url(self._href)
            if title and url:
                self.results.append({"title": html.unescape(title), "url": url, "snippet": ""})
            self._capture = ""
        elif self._capture == "snippet" and tag in {"a", "div"}:
            snippet = html.unescape(" ".join("".join(self._text).split()))
            if snippet and self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = snippet
            self._capture = ""

    @staticmethod
    def _decode_url(value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        redirected = parse_qs(parsed.query).get("uddg", [])
        return unquote(redirected[0]) if redirected else value


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self.text).split())


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web by query or fetch a URL"

    def is_read_only(self, params=None) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    async def execute(self, query: str = "", max_results: int = 5, timeout: int = 20, **kwargs) -> ToolResult:
        try:
            q = str(query or "").strip()
            if not q:
                return ToolResult(success=False, error="Query or URL is required")

            if re.match(r"^https?://", q):
                return await self._fetch_url(q, timeout, max_results)

            limit = max(1, min(int(max_results or 5), 10))
            results = await asyncio.to_thread(self._search, q, limit)
            if not results:
                return ToolResult(success=False, error=f"No web results found for: {q}")
            lines = [f"Web search results for: {q}"]
            for item in results:
                line = f"- [{item['title']}]({item['url']})"
                if item.get("snippet"):
                    line += f"  {item['snippet']}"
                lines.append(line)
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _fetch_url(self, url: str, timeout: int, max_chars: int) -> ToolResult:
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NEXUS/1.0; +local-agent)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: urlopen(req, timeout=max(5, timeout or 20)))
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw:
                return ToolResult(success=False, error=f"Empty response from {url}")
            clean = self._strip_html(raw)
            if len(clean) > max_chars * 1000:
                clean = clean[: max_chars * 1000] + "\n... (truncated)"
            return ToolResult(
                success=True,
                output=clean[:100000],
                metadata={"status": resp.status, "url": url, "chars": len(clean)},
            )
        except urlerror.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP {e.code}: {e.reason} for {url}")
        except urlerror.URLError as e:
            return ToolResult(success=False, error=f"Connection failed: {e.reason}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    @staticmethod
    def _strip_html(raw: str) -> str:
        raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw

    @staticmethod
    def _search(query: str, limit: int) -> list[dict[str, str]]:
        route = "news/search" if "news" in query.lower() or "headline" in query.lower() else "search"
        rss_endpoint = f"https://www.bing.com/{route}?{urlencode({'q': query, 'format': 'rss'})}"
        rss_request = Request(
            rss_endpoint,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NEXUS/1.0; +local-agent)"},
        )
        try:
            with urlopen(rss_request, timeout=15) as response:
                rss_document = response.read()
            root = _xml_fromstring(rss_document)
            results: list[dict[str, str]] = []
            for item in root.findall(".//item"):
                title = html.unescape(" ".join(item.findtext("title", default="").split()))
                url = item.findtext("link", default="").strip()
                raw_description = item.findtext("description", default="")
                snippet_parser = _PlainTextParser()
                snippet_parser.feed(raw_description)
                snippet = snippet_parser.get_text()
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            if results:
                return results[:limit]
        except Exception:
            logger.warning("Bing RSS failed, falling back to DuckDuckGo")

        endpoint = f"https://html.duckduckgo.com/html/?{urlencode({'q': query})}"
        request = Request(
            endpoint,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; NEXUS/1.0; +local-agent)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urlopen(request, timeout=15) as response:
            document = response.read().decode("utf-8", errors="replace")
        parser = _DuckDuckGoResultsParser()
        parser.feed(document)
        return parser.results[:limit]
