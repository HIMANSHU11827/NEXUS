# Security

Security policies, secret scanning, and release hygiene.

**Version:** 2.0.0

## Components
- `secret_scanner.py` — `SecretScanner`: detects API keys (OpenRouter, Google, GitHub, Slack, generic sk-)
- Scans all project files excluding `.git`, `__pycache__`, `node_modules`, `dist`, `logs`, etc.
- Path traversal protection (rejects paths that escape project root)
- Public key whitelist support; skips `${...}` env var references

## Related Security Infrastructure
- `sandbox/risk.py` — CommandRiskScorer (3 tiers, 8 regex rules)
- `tools/threat_patterns.py` — Content-level threat detection (41 regex patterns, 3 scopes)
- `plugins/trust.py` — Plugin trust model with install opt-in
- `safety/` — Sovereign laws + logic prover
- `mcp/security.py` — MCP security boundary
