# Tools

NEXUS AI tool system. Each tool in its own folder with \.jsnol\ definition, \scripts/\, and \.md\ docs.

**Version:** 1.0.0

## Structure
\tools/
  <toolname>/
    <toolname>.jsnol    - JSON tool definition (metadata + version)
    scripts/<tool>.py   - Implementation with __version__
    <toolname>.md       - Documentation
\
## Available Tools
- `bash` — Execute shell commands in a sandboxed environment
- `code_search` — Search code with glob patterns and regex, analyze code structure
- `creating` — Create a new file with content
- `deep_research` — Spawn dedicated research sub-agents to investigate a topic
- `deleting` — Delete a file
- `git_ops` — Inspect repository state, branches, diffs, logs, and tracked files
- `hive` — Spawn dedicated sub-agents for complex multi-step tasks
- `knowledge` — Query the NEXUS knowledge base with semantic search
- `memory` — Store, retrieve, search, and manage short and long-term memories
- `modifying` — Edit text in an existing file
- `planning` — Write a TODO LIST plan to todo.md
- `reading` — Read file contents
- `reasoning` — Deep chain-of-thought reasoning and problem decomposition
- `shortcuts` — Quick utility helpers: list, pwd, tree, info, find
- `system` — Monitor system resources, audit configuration, and run diagnostics
- `task` — Create, track, manage, and complete tasks with dependencies
- `terminal` — Run shell commands through the sandboxed command path
- `test_runner` — Run targeted test commands for Python, Node, or generic checks
- `web_search` — Search the web by query or fetch a URL
