"""
NEXUS Knowledge System
- KnowledgeVault: encrypted persistent fact storage with importance scoring
- Library: curated documentation harvested from external sources
- Atlas Index: AST-based code symbol index
- RAG Index: BM25-based document retrieval
- LSP Symbol Map: workspace-wide symbol resolution
- Deep Index: unified symbol + chunk FTS5 search
"""
from knowledge.vault import KnowledgeVault

__all__ = ["KnowledgeVault"]
