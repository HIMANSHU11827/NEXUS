# NEXUS MCP Code Graph

NEXUS exposes its codebase knowledge graph through a small stdio MCP server.
This gives MCP-capable agents structural codebase context without rereading the
whole repository.

## Start

```powershell
nexus-mcp
```

> **Note**: `nexus-mcp` and `python -m mcp.server` launch the **full NEXUS tool
> server** (`mcp/server/` package — `NEXUSMCPServer`), which exposes every
> registered NEXUS tool over stdio MCP. The code-graph tools below belong to the
> **legacy** `mcp/server.py` module, which is shadowed by the `mcp/server/`
> package under Python's import rules. To run the code-graph server directly,
> execute the module as a file:

```powershell
python mcp/server.py
```

If the package is not installed in editable mode yet:

```powershell
python -m pip install -e ".[dev]"
nexus-mcp
```

## Manual MCP Command

Use this command in MCP clients that accept a command/args pair:

```json
{
  "command": "python",
  "args": ["-m", "mcp.server"]
}
```

## Tools

- `nexus_code_graph_build`: index the current repo.
- `nexus_code_graph_summary`: counts, edge types, and top hubs.
- `nexus_code_graph_search`: find files and symbols.
- `nexus_code_graph_dependencies`: what a target depends on.
- `nexus_code_graph_dependents`: what depends on a target.
- `nexus_code_graph_symbol_context`: definitions, dependencies, and dependents for a symbol.

## Current Scope

The graph supports Python, TypeScript, TSX, JavaScript, and JSX files. Python
gets AST-based functions, classes, methods, imports, inheritance, and call edges.
JS/TS currently gets import and symbol-definition edges through lightweight
parsing. Tree-sitter-style deep JS/TS call graphs are a planned upgrade.

