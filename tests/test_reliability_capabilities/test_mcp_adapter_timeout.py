"""Capabilities hardening: MCP adapter timeout configuration.

The hard-coded 30s default must be tunable via NEXUS_MCP_TOOL_TIMEOUT_S
(min 1s, float), with the tool definition's own ``timeout`` winning.
"""

from extensions.tools.built_in.nexus_tools.mcp_adapter import MCPToolAdapter, _mcp_timeout_default


def _adapter(env_value=None, tool_timeout=None, monkeypatch=None):
    if env_value is None:
        monkeypatch.delenv("NEXUS_MCP_TOOL_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("NEXUS_MCP_TOOL_TIMEOUT_S", env_value)
    tool_def = {"name": "sample"}
    if tool_timeout is not None:
        tool_def["timeout"] = tool_timeout
    return MCPToolAdapter("sample", object(), tool_def)


def test_env_timeout_used_when_tool_def_has_no_timeout(monkeypatch):
    adapter = _adapter(env_value="7.5", monkeypatch=monkeypatch)
    assert adapter._timeout_s == 7.5


def test_default_timeout_when_env_unset(monkeypatch):
    adapter = _adapter(env_value=None, monkeypatch=monkeypatch)
    assert adapter._timeout_s == 30


def test_tool_definition_timeout_wins_over_env(monkeypatch):
    adapter = _adapter(env_value="7.5", tool_timeout=12, monkeypatch=monkeypatch)
    assert adapter._timeout_s == 12


def test_invalid_env_falls_back_to_default(monkeypatch):
    assert _mcp_timeout_default() == 30.0
    monkeypatch.setenv("NEXUS_MCP_TOOL_TIMEOUT_S", "not-a-number")
    assert _mcp_timeout_default() == 30.0
    adapter = _adapter(env_value="not-a-number", monkeypatch=monkeypatch)
    assert adapter._timeout_s == 30


def test_sub_minimum_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NEXUS_MCP_TOOL_TIMEOUT_S", "0.5")
    assert _mcp_timeout_default() == 30.0
    adapter = _adapter(env_value="0.5", monkeypatch=monkeypatch)
    assert adapter._timeout_s == 30


def test_float_env_accepted(monkeypatch):
    monkeypatch.setenv("NEXUS_MCP_TOOL_TIMEOUT_S", "3.25")
    assert _mcp_timeout_default() == 3.25