from .base_tool import BaseTool, ToolResult
from typing import Dict, Any

class AtlasTool(BaseTool):
    """
    NEXUS ATLAS TOOL — NEXT-GEN ARCHITECTURAL GROUNDING
    Fuses AST Logic with semantic RAG to find code patterns, symbols, and logic.
    """

    def __init__(self, root_dir: str = "."):
        self.root = root_dir
        self.name = "rag"
        self.description = "Performs next-gen RAG. Input: 'query'. Finds definitive code symbols and high-precision snippets."
        self.aliases = ["atlas", "search_code"]

    def call(self, **kwargs) -> ToolResult:
        query = kwargs.get("query")
        if not query:
            return ToolResult(error="Missing required parameter: 'query'")
        
        from rag.engine import NexusAtlasRAG
        rag = NexusAtlasRAG()
        # Prefer Turbo Search if possible, fall back to BM25
        try:
            res = rag.turbo_search(query)
        except Exception as e:
            print(f"[ATLAS_TOOL]: turbo_search failed ({e}) — falling back to BM25")
            res = rag.retrieve_as_text(query)
        else:
            if "No matches found" in res:
                res = rag.retrieve_as_text(query)
            
        return ToolResult(data=f"### [NEXUS ATLAS RAG ACTIVE]\n{res}")

    def is_read_only(self, input_data: Dict[str, Any] = None) -> bool:
        return True

class AtlasMapTool(BaseTool):
    """
    NEXUS ATLAS MAP — COGNITIVE ARCHITECTURE VIEW
    Generates a high-level map of a directory's internal logic, functions, and classes.
    """

    def __init__(self, root_dir: str = "."):
        self.root = root_dir
        self.name = "atlas_map"
        self.description = "Generates a logic map of a directory. Input: 'dir'. Use this to understand codebase architecture."
        self.aliases = ["map_logic", "cognitive_map"]

    def call(self, **kwargs) -> ToolResult:
        target_dir = kwargs.get("dir", ".")
        from rag.atlas.mapper import AtlasCognitiveMapper
        mapper = AtlasCognitiveMapper(self.root)
        res = mapper.map_directory(target_dir)
        return ToolResult(data=res)

    def is_read_only(self, input_data: Dict[str, Any] = None) -> bool:
        return True
