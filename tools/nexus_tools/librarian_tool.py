import os
import requests
import logging
from bs4 import BeautifulSoup
from typing import Dict, Any, List
from .base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)

class LibrarianTool(BaseTool):
    """
    NEXUS LIBRARIAN — Autonomous Documentation Harvester.
    Crawls documentation websites, extracts text, and converts to local Markdown for the RAG index.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "librarian_harvest"
        self.description = (
            "Harvests documentation from a URL and stores it locally for RAG. "
            "Params: 'url' (str), 'category' (str - e.g. 'react', 'python')."
        )
        self.library_dir = os.path.join(self.root, "knowledge", "library")
        os.makedirs(self.library_dir, exist_ok=True)

    def call(self, **kwargs) -> ToolResult:
        url = kwargs.get("url")
        category = kwargs.get("category", "general")
        
        if not url:
            return ToolResult(error="URL is required for harvesting.")

        try:
            # We use a simple GET request for now; in the future, we could use a browser agent
            headers = {"User-Agent": "NEXUS-Librarian/1.0 (Autonomous Cognitive Harvester)"}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove noise
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            
            text = soup.get_text(separator='\n')
            title = soup.title.string if soup.title else "Untitled_Documentation"
            clean_title = "".join([c if c.isalnum() else "_" for c in title])
            
            # Store as Markdown
            cat_dir = os.path.join(self.library_dir, category)
            os.makedirs(cat_dir, exist_ok=True)
            
            file_path = os.path.join(cat_dir, f"{clean_title}.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# SOURCE: {url}\n\n")
                f.write(text)
            
            # Refresh Atlas (RAG) Index
            try:
                from core.kernel import get_nexus_kernel
                kernel = get_nexus_kernel()
                kernel.rag.index_workspace() # Re-index everyone
            except:
                pass

            return ToolResult(data=f"[LIBRARIAN_SUCCESS]: Harvested '{title}' to knowledge/library/{category}/")
        except Exception as e:
            logger.error(f"[LIBRARIAN_ERROR]: Failed to harvest {url}: {e}")
            return ToolResult(error=str(e))
