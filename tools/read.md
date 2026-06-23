# Tools

NEXUS AI tool system. Each tool in its own folder with `.jsnol` definition, `scripts/`, and `.md` docs.

## Structure
```
tools/
  <toolname>/
    <toolname>.jsnol    — JSON tool definition
    scripts/<tool>.py   — Implementation
    <toolname>.md       — Documentation
```

## Available Tools
- `bash` — Shell execution
- `code_search` — Glob/grep code search
- `file_ops` — File read/write/edit
- `knowledge` — Knowledge base queries
- `mcp` — MCP server management
- `memory` — Memory store/retrieve
- `reasoning` — Chain-of-thought
- `system` — System monitoring
- `task` — Task management
- `web_search` — Web search/fetch
