from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import html
import ipaddress
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from socket import SOCK_STREAM, getaddrinfo
from urllib import error as urlerror
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, ProxyHandler, build_opener, urlopen

try:
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:
    from xml.etree.ElementTree import fromstring as _xml_fromstring

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("nexus.tools.web_search")

# urllib automatically inherits HTTP(S)_PROXY/ALL_PROXY from the machine.
# On this workstation those variables point to a stopped localhost proxy,
# which caused every search to fail with WinError 10061. NEXUS web search
# uses direct HTTPS by default; operators who require a corporate proxy can
# opt back in with NEXUS_WEB_USE_PROXY=1.
_DIRECT_OPENER = build_opener(ProxyHandler({}))

#: Bounded retry policy for transient network failures (timeouts, refused
#: connections, DNS failures, HTTP 429 / 5xx).  Permanent failures (HTTP 4xx
#: other than 429, malformed URLs) and the SSRF guard are never retried.
_WEB_SEARCH_MAX_ATTEMPTS_DEFAULT = 3
_WEB_SEARCH_BACKOFF_BASE_DEFAULT = 0.5
_WEB_SEARCH_BACKOFF_MULTIPLIER = 2.0
_WEB_SEARCH_JITTER = 0.25
_WEB_SEARCH_MAX_DELAY = 10.0


def _web_retry_policy() -> tuple[int, float]:
    """Return ``(max_attempts, backoff_base)`` from env, falling back to defaults."""
    max_attempts = _WEB_SEARCH_MAX_ATTEMPTS_DEFAULT
    raw_attempts = os.environ.get("NEXUS_WEB_SEARCH_MAX_ATTEMPTS", "")
    if raw_attempts:
        try:
            max_attempts = max(1, int(float(raw_attempts)))
        except (TypeError, ValueError):
            logger.warning("Invalid NEXUS_WEB_SEARCH_MAX_ATTEMPTS=%r; using default", raw_attempts)
    backoff_base = _WEB_SEARCH_BACKOFF_BASE_DEFAULT
    raw_base = os.environ.get("NEXUS_WEB_SEARCH_BACKOFF_BASE", "")
    if raw_base:
        try:
            backoff_base = max(0.0, float(raw_base))
        except (TypeError, ValueError):
            logger.warning("Invalid NEXUS_WEB_SEARCH_BACKOFF_BASE=%r; using default", raw_base)
    return max_attempts, backoff_base


_WEB_SEARCH_MAX_ATTEMPTS, _WEB_SEARCH_BACKOFF_BASE = _web_retry_policy()


def _is_transient_failure(exc: BaseException) -> bool:
    """True only for network failures worth a bounded retry."""
    if isinstance(exc, urlerror.HTTPError):
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, urlerror.URLError):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return False


def _retry_transient(fn, *args, **kwargs):
    """Call ``fn`` with bounded exponential backoff + jitter on transient failures.

    Permanent errors and the final transient failure propagate unchanged.
    Sleeps are bounded by ``_WEB_SEARCH_MAX_DELAY`` so a retry storm can never
    exceed the per-attempt budget by more than a fixed ceiling.
    """
    delay = _WEB_SEARCH_BACKOFF_BASE
    for attempt in range(_WEB_SEARCH_MAX_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not _is_transient_failure(exc) or attempt + 1 >= _WEB_SEARCH_MAX_ATTEMPTS:
                raise
            sleep_for = min(delay + random.uniform(0, _WEB_SEARCH_JITTER), _WEB_SEARCH_MAX_DELAY)
            logger.warning(
                "web_search transient failure (attempt %d/%d): %s — retrying in %.2fs",
                attempt + 1,
                _WEB_SEARCH_MAX_ATTEMPTS,
                exc,
                sleep_for,
            )
            time.sleep(sleep_for)
            delay = min(delay * _WEB_SEARCH_BACKOFF_MULTIPLIER, _WEB_SEARCH_MAX_DELAY)
    raise RuntimeError("unreachable")  # pragma: no cover


def _read_url(request: Request, timeout: int) -> bytes:
    """Perform and fully consume one blocking urllib response."""
    with _open_url(request, timeout=timeout) as response:
        return response.read()


def _open_url(request: Request, timeout: int):
    if os.environ.get("NEXUS_WEB_USE_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}:
        return urlopen(request, timeout=timeout)
    return _DIRECT_OPENER.open(request, timeout=timeout)


def _fetch_response(request: Request, timeout: int) -> tuple[int, bytes]:
    """Perform and fully consume one blocking urllib response."""
    with _open_url(request, timeout=timeout) as response:
        return int(getattr(response, "status", 200)), response.read()


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


#: SSRF guard for direct URL fetches. Fetching is only allowed to public
#: internet destinations unless the operator explicitly opts in to private
#: fetches (NEXUS_WEB_FETCH_ALLOW_PRIVATE=1) for local development.
_PRIVATE_FETCH_ALLOWED = os.environ.get("NEXUS_WEB_FETCH_ALLOW_PRIVATE", "").strip().lower() in {
    "1", "true", "yes", "on"
}

#: Well-known cloud metadata hostnames (in addition to 169.254.169.254) that
#: must never be fetched, even if they resolve to public-looking IPs.
_CLOUD_METADATA_HOSTS = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.azure.internal",
    "instance-data",
    "instance-data.ec2.internal",
    "167.254.169.254",
})


def _ssrf_block_reason(url: str) -> str | None:
    """Return a reason string if ``url`` must not be fetched, else ``None``.

    Uses ipaddress + DNS resolution, so loopback, private, link-local,
    reserved, multicast, and unspecified targets are all refused. When a
    hostname cannot be resolved we refuse as well (fail closed).
    """
    if _PRIVATE_FETCH_ALLOWED:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return f"unsupported scheme: {parsed.scheme or 'none'}"
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "URL has no hostname"
    if host in _CLOUD_METADATA_HOSTS:
        return "cloud metadata endpoint is blocked"
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "invalid port in URL"
    try:
        resolved = getaddrinfo(host, port, type=SOCK_STREAM)
    except OSError:
        return "hostname could not be resolved"
    for info in resolved:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if not ip.is_global:
            return f"internal/private address blocked: {ip}"
    return None


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
            attempted = [q]
            lowered = q.lower()
            if "today" in lowered:
                attempted.append(re.sub(r"\btoday\b", "latest", q, flags=re.IGNORECASE))
                attempted.append(
                    f"{q} {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
                )
            elif "latest" not in lowered and "breaking" in lowered:
                attempted.append(f"{q} latest")
            results = []
            used_query = q
            for candidate in dict.fromkeys(attempted):
                results = await asyncio.to_thread(self._search, candidate, limit)
                if results:
                    used_query = candidate
                    break
            if not results:
                return ToolResult(
                    success=False,
                    error=f"No web results found after trying: {', '.join(dict.fromkeys(attempted))}",
                    metadata={"attempted_queries": list(dict.fromkeys(attempted))},
                )
            lines = [f"Web search results for: {used_query}"]
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
            # DNS resolution is synchronous too; keep the complete network
            # boundary off the event loop, not only the final HTTP request.
            block = await asyncio.to_thread(_ssrf_block_reason, url)
            if block:
                return ToolResult(
                    success=False,
                    error=f"URL fetch blocked (SSRF guard): {block}",
                    metadata={"url": url},
                )
            req = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NEXUS/1.0; +local-agent)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            status, payload = await asyncio.to_thread(
                _retry_transient, _fetch_response, req, max(5, timeout or 20)
            )
            raw = payload.decode("utf-8", errors="replace")
            if not raw:
                return ToolResult(success=False, error=f"Empty response from {url}")
            clean = self._strip_html(raw)
            if len(clean) > max_chars * 1000:
                clean = clean[: max_chars * 1000] + "\n... (truncated)"
            return ToolResult(
                success=True,
                output=clean[:100000],
                metadata={"status": status, "url": url, "chars": len(clean)},
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
            rss_document = _retry_transient(_read_url, rss_request, 15)
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
        document = _retry_transient(_read_url, request, 15).decode("utf-8", errors="replace")
        parser = _DuckDuckGoResultsParser()
        parser.feed(document)
        return parser.results[:limit]
