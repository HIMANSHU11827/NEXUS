# RAG Engine

Retrieval-Augmented Generation pipeline — BM25 + SimHash vector retrieval with Atlas deep indexing.

**Version:** 2.0.0

## Capabilities
- Persistent BM25 keyword index with inverted index + IDF cache, incremental updates
- Hybrid keyword/vector result blending (SimHash-based approximate vectors)
- Turbo vector engine (SimHash, Hamming distance search)
- Deep indexer (SQLite FTS5 unified index with AST symbol extraction)
- Atlas engine (AST-based symbol indexing + BM25 retrieval)
- Atlas store (FTS5 fact store) + atlas mapper (structural directory mapping)
- Stale entry cleanup, document chunking, workspace indexing