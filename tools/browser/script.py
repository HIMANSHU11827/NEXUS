"""
NEXUS WEB SEARCH + READER 2.0
Searches the internet via DuckDuckGo (no API key needed) and reads pages.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Any
from core.nexus_compat import import_requests, import_bs4, s, sx  # type: ignore
import urllib.parse

_requests = import_requests()
_bs4 = import_bs4()
BeautifulSoup: Any = _bs4.BeautifulSoup


class BrowserTool:
    """NEXUS WEB SEARCH + READER — Zero API key required."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    def search(self, query: str, max_results: int = 5) -> str:
        """
        Search DuckDuckGo for a query and return title + snippet for top results.
        No API key needed — uses the HTML endpoint.
        """
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            res = _requests.get(url, headers=self.HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")

            results = []
            for r in s(soup.select(".result"), max_results):
                title_tag = r.select_one(".result__title")
                snippet_tag = r.select_one(".result__snippet")
                link_tag = r.select_one(".result__url")

                title = title_tag.get_text(strip=True) if title_tag else "No title"
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                link = link_tag.get_text(strip=True) if link_tag else ""

                results.append(f"**{title}**\n{link}\n{snippet}")

            return "\n\n".join(results) if results else "No results found."
        except Exception as e:
            return f"Search error: {str(e)}"

    def read_url(self, url: str, max_chars: int = 3000) -> str:
        """Fetch a URL and return readable plain text (no JS required)."""
        try:
            if not url.startswith("http"):
                url = "https://" + url
            res = _requests.get(url, headers=self.HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Truncate to avoid context overflow
            return s(text, max_chars) + ("..." if len(text) > max_chars else "")
        except Exception as e:
            return f"Read error: {str(e)}"

    def search_and_read(self, query: str) -> str:
        """Search, take the first result, and read its full content."""
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            res = _requests.get(url, headers=self.HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")

            first = soup.select_one(".result__a")
            if not first:
                return "No results found."

            href = first.get("href", "")
            # DuckDuckGo wraps URLs — extract the real URL
            if "uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=")[-1].split("&")[0])

            summary = self.search(query, max_results=3)
            page_content = self.read_url(href)
            return f"[Search Results]\n{summary}\n\n[Top Page Content]\n{page_content}"
        except Exception as e:
            return f"Error: {str(e)}"


if __name__ == "__main__":
    b = BrowserTool()
    print(b.search("Python 3.14 new features"))
