"""NEXUS Tools System — Canonical entry point.

All tool registration, discovery, execution, and lifecycle management
flows through this module. The implementation lives in nexus_tools/ for
modularity; this __init__.py re-exports the public API.

Public API
----------
- BaseTool              — Abstract base class for all tools
- ToolResult            — Legacy dataclass result (backward compat)
- ToolCallResult        — Canonical dict-compatible result envelope
- ToolEntry             — Registered tool metadata + execution policy
- ToolRegistry          — Discovery, registration, execution manager
- ToolArgumentError     — Raised when tool arguments cannot be parsed
- classify_error        — Classify exceptions as retryable/non-retryable
- normalize_result      — Normalize raw outputs into ToolCallResult
- parse_tool_arguments  — Parse & repair model-produced JSON arguments
- start_envelope        — Create tool call timing envelope
- finish_envelope       — Finalize timing envelope on ToolCallResult
- DEFAULT_MAX_OUTPUT_CHARS — Cap for captured tool output
- STATUS_OK / STATUS_ERROR / STATUS_TIMEOUT / STATUS_UNIMPLEMENTED / STATUS_BLOCKED

Modes of Registration
---------------------
1. **Auto-discovery**: tools/<name>/<name>.jsnol + scripts/*.py (BaseTool subclass)
2. **Plugins**: PluginToolAdapter wraps callables into BaseTool
3. **MCP**: MCPToolAdapter bridges MCPClient.call_tool() into BaseTool
4. **Skills**: Skills register as tools via SkillToolAdapter
"""

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.call_parser import parse_all_tool_calls, parse_single_tool_call
from tools.nexus_tools.mcp_adapter import MCPToolAdapter
from tools.nexus_tools.registry import CancellationToken, ToolEntry, ToolRegistry
from tools.nexus_tools.result import (
    DEFAULT_MAX_OUTPUT_CHARS,
    STATUS_BLOCKED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_TIMEOUT,
    STATUS_UNIMPLEMENTED,
    ToolArgumentError,
    ToolCallResult,
    classify_error,
    finish_envelope,
    normalize_result,
    parse_tool_arguments,
    start_envelope,
)
from tools.nexus_tools.skill_adapter import SkillExecutor, SkillToolAdapter

__all__ = [
    # Core classes
    "BaseTool",
    "ToolResult",
    "ToolCallResult",
    "ToolEntry",
    "ToolRegistry",
    "ToolArgumentError",
    "CancellationToken",
    # Adapters
    "MCPToolAdapter",
    "SkillToolAdapter",
    "SkillExecutor",
    # Call parser
    "parse_single_tool_call",
    "parse_all_tool_calls",
    # Result functions
    "classify_error",
    "normalize_result",
    "parse_tool_arguments",
    "start_envelope",
    "finish_envelope",
    # Constants
    "DEFAULT_MAX_OUTPUT_CHARS",
    "STATUS_OK",
    "STATUS_ERROR",
    "STATUS_TIMEOUT",
    "STATUS_UNIMPLEMENTED",
    "STATUS_BLOCKED",
]


