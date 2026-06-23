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
- \ash\ — Shell execution
- \code_search\ — Glob/grep code search
- \ile_ops\ — File read/write/edit
- \knowledge\ — Knowledge base queries
- \mcp\ — MCP server management
- \memory\ — Memory store/retrieve
- easoning\ — Chain-of-thought
- \system\ — System monitoring
- \	ask\ — Task management
- \web_search\ — Web search/fetch
