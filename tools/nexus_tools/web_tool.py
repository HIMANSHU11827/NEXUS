"""
NEXUS WEB TOOL — Claude Code WebFetchTool + WebSearchTool combined.
"""

import urllib.parse
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web using DuckDuckGo (no API key needed)."
    aliases = ["search_web", "google"]

    def call(self, query: str = "", max_results: int = 5, **kwargs) -> ToolResult:
        if not query:
            return ToolResult(error="No search query provided")
        try:
            from tools.browser.script import BrowserTool

            browser = BrowserTool()
            results = browser.search(query, max_results)
            return ToolResult(data=results)
        except Exception as e:
            return ToolResult(error=str(e))

    def is_read_only(self, input_data=None):
        return True


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a URL and return readable text content."
    aliases = ["fetch", "read_url"]

    def call(self, url: str = "", max_chars: int = 3000, **kwargs) -> ToolResult:
        if not url:
            return ToolResult(error="No URL provided")
        try:
            from tools.browser.script import BrowserTool

            browser = BrowserTool()
            content = browser.read_url(url, max_chars)
            return ToolResult(data=content)
        except Exception as e:
            return ToolResult(error=str(e))

    def is_read_only(self, input_data=None):
        return True
