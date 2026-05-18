# SECURITY SKILL (GOD-ARCHITECT)

## OBJECTIVE
Perform automated vulnerability scanning and ensure strict credential protection and environment safety.

## INSTRUCTIONS
1.  **Leakage Check**: Explicitly search for `.env`, `git/config`, or raw API keys via ```bash``` (using `grep` or `find`).
2.  **Logic-Prover Audit**: Update `safety/prover.py` if new dangerous shell patterns are discovered.
3.  **Credential Rotation**: If a key is leaked, immediately use `EDIT_FILE` to redact it and propose a rotation plan.
4.  **Static Analysis**: Check for `eval()`, `exec()`, or dangerous `subprocess` calls in any code snippet.

## USAGE
```bash
grep -rnE "[0-9a-zA-Z]{32}" .
LSP_CHECK('providers/router.py')
```
---
# PERFORMANCE SKILL (GOD-ARCHITECT)

## OBJECTIVE
Optimize NEXUS cognitive trajectories and execution speeds by profiling the parallel loop.

## INSTRUCTIONS
1.  **Parallel Bottlenecks**: Identify tools in the coordinator's `ThreadPoolExecutor` that are blocking turn-latency.
2.  **Context Micro-compaction**: Identify tool results that are exceeding 2500 chars and fine-tune their summaries.
3.  **Model Latency Check**: Monitor the `router.py` log to check if cloud-fallback is occurring too frequently.
4.  **Caching**: Implement local file-caching in tools (e.g., `BrowserTool`) to avoid redundant requests.

## USAGE
```python
RAG_QUERY('performance profiling for python orchestrators')
EDIT_FILE('orchestrators/coordinator.py', 'MAX_WORKERS=5', 'MAX_WORKERS=10', True)
```
