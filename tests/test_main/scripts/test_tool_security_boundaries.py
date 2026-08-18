import asyncio
import io
from unittest.mock import MagicMock, patch

import pytest

from extensions.mcp.core.client import MCPClient
from extensions.mcp.core.security import (
    bounded_int,
    read_bounded_line,
    redact_secret_text,
    workspace_root,
)
from extensions.plugins.built_in.trust import PluginInstallDisabled, require_unverified_install_opt_in
from extensions.skills.built_in.registry import SkillRegistry
from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult
from extensions.tools.built_in.nexus_tools.registry import ToolEntry, ToolRegistry


class RecordingTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(output="ok")


def registry_with(entry: ToolEntry) -> ToolRegistry:
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.root = "."
    registry._tools = {entry.name: entry}
    return registry


def test_registry_rejects_unavailable_tool_before_execution(monkeypatch):
    monkeypatch.delenv("NEXUS_TEST_REQUIRED_KEY", raising=False)
    tool = RecordingTool()
    entry = ToolEntry("guarded", {"params": {}}, tool, requires_env=["NEXUS_TEST_REQUIRED_KEY"])

    with pytest.raises(RuntimeError, match="NEXUS_TEST_REQUIRED_KEY"):
        asyncio.run(registry_with(entry).execute("guarded"))

    assert tool.calls == []


@pytest.mark.parametrize(
    ("params", "error"),
    [({}, ValueError), ({"count": "many"}, TypeError), ({"count": True}, TypeError)],
)
def test_registry_validates_required_and_typed_params(params, error):
    tool = RecordingTool()
    entry = ToolEntry(
        "typed",
        {"params": {"count": {"type": "integer", "required": True}}},
        tool,
    )

    with pytest.raises(error):
        asyncio.run(registry_with(entry).execute("typed", **params))

    assert tool.calls == []


def test_registry_executes_valid_typed_params():
    tool = RecordingTool()
    entry = ToolEntry(
        "typed",
        {"params": {"count": {"type": "integer", "required": True}}},
        tool,
    )

    result = asyncio.run(registry_with(entry).execute("typed", count=3))

    assert result.success is True
    assert tool.calls == [{"count": 3}]


def test_registry_coerces_safe_scalar_params_before_validation():
    tool = RecordingTool()
    entry = ToolEntry(
        "typed",
        {
            "params": {
                "count": {"type": "integer", "required": True},
                "ratio": {"type": "number"},
                "enabled": {"type": "boolean"},
            }
        },
        tool,
    )

    result = asyncio.run(
        registry_with(entry).execute("typed", count="3", ratio="1.5", enabled="true")
    )

    assert result.success is True
    assert tool.calls == [{"count": 3, "ratio": 1.5, "enabled": True}]


def test_registry_applies_jsnol_defaults_before_execution():
    tool = RecordingTool()
    entry = ToolEntry(
        "defaulted",
        {
            "params": {
                "query": {"type": "string", "required": True},
                "limit": {"type": "integer", "default": 10},
            },
            "execution": {"defaults": {"query": "status"}},
        },
        tool,
    )

    result = asyncio.run(registry_with(entry).execute("defaulted"))

    assert result.success is True
    assert tool.calls == [{"query": "status", "limit": 10}]


def test_registry_reads_execution_policy_from_jsnol_schema():
    tool = RecordingTool()
    entry = ToolEntry(
        "parallel_tool",
        {
            "params": {},
            "execution": {
                "parallel": True,
                "max_parallel": 7,
                "cooldown_ms": 25,
            },
        },
        tool,
    )

    assert entry.is_concurrency_safe() is True
    assert entry.max_parallel == 7
    assert entry.cooldown_ms == 25


def test_registry_reads_constitution_for_any_tool():
    tool = RecordingTool()
    entry = ToolEntry(
        "constitutional_tool",
        {
            "params": {},
            "constitution": {
                "intent": "inspect project files safely",
                "rules": ["read before editing", "hide raw secrets"],
                "conditions": ["only run inside workspace"],
                "one_time_use": True,
                "max_per_task": 2,
                "parallel": False,
                "max_parallel": 3,
            },
            "execution": {"cooldown_ms": 15},
        },
        tool,
    )

    tools = registry_with(entry).list_tools(include_unavailable=True)

    assert entry.intent == "inspect project files safely"
    assert entry.rules == ["read before editing", "hide raw secrets"]
    assert entry.conditions == ["only run inside workspace"]
    assert entry.one_time_use is True
    assert entry.max_per_task == 2
    assert entry.max_parallel == 3
    assert entry.cooldown_ms == 15
    assert tools["constitutional_tool"]["constitution"]["rules"] == ["read before editing", "hide raw secrets"]


def test_registry_honors_disabled_constitution():
    entry = ToolEntry("disabled_tool", {"params": {}, "constitution": {"enabled": False}}, RecordingTool())

    assert entry.is_available() is False
    assert registry_with(entry).list_tools() == {}


def test_mcp_root_cannot_escape_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = workspace / "child"
    child.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("NEXUS_MCP_ALLOWED_ROOT", str(workspace))

    assert workspace_root({"root": "child"}) == str(child.resolve())
    with pytest.raises(ValueError, match="outside NEXUS_MCP_ALLOWED_ROOT"):
        workspace_root({"root": str(outside)})


@pytest.mark.parametrize("value", [0, 201, True, "not-a-number"])
def test_mcp_limits_reject_invalid_or_excessive_values(value):
    with pytest.raises(ValueError):
        bounded_int({"limit": value}, "limit", 20, 200)


def test_mcp_client_never_uses_a_shell():
    client = MCPClient("server executable", ["arg with spaces", "&& harmless-as-argument"])
    process = MagicMock()
    process.stdout.readline.return_value = ""
    process.stderr.readline.return_value = ""
    with patch("extensions.mcp.core.client.scripts.client.subprocess.Popen", return_value=process) as popen, patch.object(
        client, "call", return_value=None
    ):
        client.start()

    assert popen.call_args.kwargs["shell"] is False
    assert popen.call_args.args[0] == [
        "server executable",
        "arg with spaces",
        "&& harmless-as-argument",
    ]


def test_mcp_client_failed_initialize_stops_process():
    client = MCPClient("server executable", [])
    process = MagicMock()
    process.stdout.readline.return_value = ""
    process.stderr.readline.return_value = ""
    with patch("extensions.mcp.core.client.scripts.client.subprocess.Popen", return_value=process), patch.object(
        client, "call", return_value=None
    ):
        assert client.start() is False

    process.terminate.assert_called_once()
    assert client.process is None
    assert client._running is False


def test_mcp_client_restarts_after_process_exits():
    client = MCPClient("server executable", [])
    dead_process = MagicMock()
    dead_process.poll.return_value = 7
    dead_process.returncode = 7
    client.process = dead_process

    new_process = MagicMock()
    new_process.stdout.readline.return_value = ""
    new_process.stderr.readline.return_value = ""

    with patch("extensions.mcp.core.client.scripts.client.subprocess.Popen", return_value=new_process) as popen, patch.object(
        client, "call", return_value={"serverInfo": {"name": "ok"}}
    ):
        assert client.start() is True

    popen.assert_called_once()
    assert client.process is new_process


def test_mcp_client_start_failure_returns_false():
    client = MCPClient("missing-server", [])

    with patch("extensions.mcp.core.client.scripts.client.subprocess.Popen", side_effect=OSError("not found")):
        assert client.start() is False

    assert client.process is None
    assert client._running is False


def test_mcp_client_serializes_concurrent_start_attempts():
    from concurrent.futures import ThreadPoolExecutor

    client = MCPClient("server executable", [])
    process = MagicMock()
    process.poll.return_value = None
    process.stdout.readline.return_value = ""
    process.stderr.readline.return_value = ""

    with patch("extensions.mcp.core.client.scripts.client.subprocess.Popen", return_value=process) as popen, patch.object(
        client, "call", return_value={"serverInfo": {"name": "ok"}}
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _ignored: client.start(), (1, 2)))

    assert results == [True, True]
    popen.assert_called_once()


@pytest.mark.parametrize("command,args", [("", []), ("bad\x00cmd", []), ("ok", ["bad\x00arg"])])
def test_mcp_client_rejects_malformed_process_arguments(command, args):
    with pytest.raises(ValueError):
        MCPClient(command, args)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer top-secret-token",
        "api_key=super-secret-value",
        "token github_pat_abcdefghijklmnopqrstuvwxyz",
        "key sk_abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_mcp_diagnostics_redact_common_secret_shapes(value):
    output = redact_secret_text(value)
    assert "secret" not in output.lower()
    assert "github_pat_" not in output
    assert "sk_" not in output


def test_mcp_line_reader_bounds_and_drains_oversized_message():
    stream = io.StringIO("x" * 20 + "\nnext\n")
    line, oversized = read_bounded_line(stream, maximum=10)
    assert line == ""
    assert oversized is True
    assert read_bounded_line(stream, maximum=10) == ("next\n", False)


def test_skill_registry_prefers_canonical_and_emits_usage_identity(tmp_path):
    canonical = tmp_path / ".opencode" / "skills" / "reviewer"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: canonical\nversion: 2.0.0\n---\nCanonical prompt",
        encoding="utf-8",
    )
    legacy = tmp_path / "skills" / "reviewer"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: legacy\n---\nLegacy prompt",
        encoding="utf-8",
    )

    records = SkillRegistry(tmp_path).discover()

    assert len(records) == 1
    assert records[0].description == "canonical"
    assert records[0].source == "opencode"
    assert records[0].usage_event()["name"] == "reviewer"
    assert records[0].usage_event()["source"] == "opencode"


def test_skill_registry_supports_legacy_flat_files(tmp_path):
    skills = tmp_path / "extensions" / "skills" / "built_in"
    skills.mkdir(parents=True)
    (skills / "legacy.md").write_text("---\nname: legacy\n---\nPrompt", encoding="utf-8")
    record = SkillRegistry(tmp_path).get("legacy")
    assert record is not None
    assert record.source == "legacy"


def test_skill_master_instances_are_keyed_by_root(tmp_path):
    from extensions.skills.built_in import NexusSkillMaster

    NexusSkillMaster._reset_instance()
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    (root_a / ".opencode" / "skills" / "alpha").mkdir(parents=True)
    (root_b / ".opencode" / "skills" / "beta").mkdir(parents=True)
    (root_a / ".opencode" / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nid: alpha\nname: alpha\n---\nA",
        encoding="utf-8",
    )
    (root_b / ".opencode" / "skills" / "beta" / "SKILL.md").write_text(
        "---\nid: beta\nname: beta\n---\nB",
        encoding="utf-8",
    )

    skills_a = {item["id"] for item in NexusSkillMaster(str(root_a)).list_skills()}
    skills_b = {item["id"] for item in NexusSkillMaster(str(root_b)).list_skills()}

    assert "alpha" in skills_a
    assert "beta" not in skills_a
    assert "beta" in skills_b
    assert "alpha" not in skills_b


def test_skill_master_delete_protects_legacy_skills_without_force(tmp_path):
    from extensions.skills.built_in import NexusSkillMaster

    NexusSkillMaster._reset_instance()
    legacy_dir = tmp_path / "extensions" / "skills" / "built_in" / "legacy"
    legacy_dir.mkdir(parents=True)
    skill_file = legacy_dir / "SKILL.md"
    skill_file.write_text("---\nid: legacy\nname: legacy\n---\nLegacy", encoding="utf-8")

    manager = NexusSkillMaster(str(tmp_path))

    assert manager.delete_skill("legacy") is False
    assert skill_file.exists()
    assert manager.delete_skill("legacy", force=True) is True
    assert not skill_file.exists()


def test_skill_master_active_prompt_honors_disabled_skill_config(tmp_path):
    from extensions.skills.built_in import NexusSkillMaster

    NexusSkillMaster._reset_instance()
    skill_root = tmp_path / ".opencode" / "skills"
    enabled = skill_root / "enabled"
    disabled = skill_root / "disabled"
    enabled.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (enabled / "SKILL.md").write_text("---\nid: enabled\nname: enabled\n---\nENABLED_PROMPT", encoding="utf-8")
    (disabled / "SKILL.md").write_text("---\nid: disabled\nname: disabled\n---\nDISABLED_PROMPT", encoding="utf-8")
    (tmp_path / "configure").mkdir()
    (tmp_path / "configure" / "settings.yml").write_text(
        "disabled_skills:\n  - disabled\n",
        encoding="utf-8",
    )

    manager = NexusSkillMaster(str(tmp_path))
    listed = {item["id"]: item for item in manager.list_skills()}

    assert listed["enabled"]["active"] is True
    assert listed["disabled"]["active"] is False
    prompt = manager.get_active_prompt()
    assert "ENABLED_PROMPT" in prompt
    assert "DISABLED_PROMPT" not in prompt


def test_skill_master_active_prompt_honors_inactive_custom_skill_config(tmp_path):
    from extensions.skills.built_in import NexusSkillMaster

    NexusSkillMaster._reset_instance()
    skill_root = tmp_path / ".opencode" / "skills" / "reviewer"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("---\nid: reviewer\nname: reviewer\n---\nREVIEW_PROMPT", encoding="utf-8")
    (tmp_path / "configure").mkdir()
    (tmp_path / "configure" / "settings.yml").write_text(
        "custom_skill_configs:\n  reviewer:\n    active: false\n",
        encoding="utf-8",
    )

    manager = NexusSkillMaster(str(tmp_path))

    assert manager.list_skills()[0]["active"] is False
    assert "REVIEW_PROMPT" not in manager.get_active_prompt()


def test_remote_plugin_install_is_fail_closed(monkeypatch):
    monkeypatch.delenv("NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL", raising=False)
    with pytest.raises(PluginInstallDisabled, match="disabled"):
        require_unverified_install_opt_in()


def test_remote_plugin_install_requires_explicit_risk_opt_in(monkeypatch):
    monkeypatch.setenv("NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL", "1")
    require_unverified_install_opt_in()
