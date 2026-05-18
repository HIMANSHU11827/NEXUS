# DEEP_SCAN SKILL (GOD-ARCHITECT)

## DISCOVERY
This skill allows NEXUS to perform a deep semantic scan of the entire repository using the RAG 3.0 engine.

## INSTRUCTIONS
1.  **Initialize**: Call `RAG_QUERY('index_workspace')` if no index exists.
2.  **Semantic Search**: Use `RAG_QUERY('<concept>')` to find all related code across the mesh.
3.  **Trace**: Follow the semantic links provided by RAG scores (0.6+ is high relevance).
4.  **Synthesize**: Provide an architectural map of how the concept is implemented across multiple files.

## USAGE
```python
RAG_QUERY('Show all implementations of the ModelRouter pattern')
```
