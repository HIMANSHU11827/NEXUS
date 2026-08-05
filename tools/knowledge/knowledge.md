# Knowledge Tool
**Version:** 2.0.0 — auto-bumped via `VersionManager` on refine.

Query, store, and manage the NEXUS knowledge base.

## Search semantics
Retrieval is **keyword-based** — substring match on query/title/content plus
term-overlap ranking. It is deliberately **not** semantic/vector search:
results are ordered by substring hits first, then term overlap. The `store`
action and the substring fallback in `query` are described accurately above;
no embeddings are computed by this tool.

## Parameters
- `action` (string, required): query | store | list | delete
- `query` (string, optional): Search query
- `title` (string, optional): Entry title
- `content` (string, optional): Entry content
