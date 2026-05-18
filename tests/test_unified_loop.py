"""
NEXUS UNIFIED LOOP UNIT TESTS
Tests for the new UnifiedCognitiveLoop architecture.
"""

import sys
import os
import tempfile
import shutil
import unittest
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestToolCall(unittest.TestCase):
    """Test ToolCall data class."""

    def test_basic_creation(self):
        from orchestrators.loop import ToolCall

        tc = ToolCall("bash", {"cmd": "ls -la"})
        self.assertEqual(tc.name, "bash")
        self.assertEqual(tc.params, {"cmd": "ls -la"})
        self.assertTrue(tc.call_id.startswith("call_"))

    def test_custom_call_id(self):
        from orchestrators.loop import ToolCall

        tc = ToolCall("file_read", {"path": "test.py"}, "custom_id")
        self.assertEqual(tc.call_id, "custom_id")

    def test_repr(self):
        from orchestrators.loop import ToolCall

        tc = ToolCall("bash", {"cmd": "ls"})
        repr_str = repr(tc)
        self.assertIn("bash", repr_str)


class TestUnifiedCognitiveLoopInit(unittest.TestCase):
    """Test UnifiedCognitiveLoop initialization."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_with_root(self):
        from orchestrators.loop import NexusLoop

        loop = NexusLoop(self.temp_dir)
        self.assertEqual(loop.root, os.path.abspath(self.temp_dir))
        self.assertEqual(loop.MAX_TURNS, 20)
        self.assertEqual(loop.COMPACT_THRESHOLD, 10)
        self.assertEqual(loop.COMPACT_KEEP, 4)

    def test_init_creates_workspace(self):
        from orchestrators.loop import NexusLoop

        loop = NexusLoop(self.temp_dir)
        workspace = os.path.join(self.temp_dir, "workspace")
        self.assertTrue(os.path.exists(workspace))

    def test_abort_flag_initially_clear(self):
        from orchestrators.loop import NexusLoop

        loop = NexusLoop(self.temp_dir)
        self.assertFalse(loop._abort_flag.is_set())


class TestExtractToolCalls(unittest.TestCase):
    """Test tool call extraction from model responses."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_json_single_call(self):
        response = 'Here is the tool call:\n```json\n{"action": "bash", "params": {"cmd": "ls"}}\n```'
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "bash")
        self.assertEqual(calls[0].params, {"cmd": "ls"})

    def test_json_multi_call(self):
        response = """```json
[
    {"action": "file_read", "params": {"path": "a.py"}},
    {"action": "file_read", "params": {"path": "b.py"}}
]
```"""
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, "file_read")
        self.assertEqual(calls[1].params, {"path": "b.py"})

    def test_bash_block(self):
        response = "Run this:\n```bash\ngit status\n```"
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "bash")
        self.assertEqual(calls[0].params, {"cmd": "git status"})

    def test_mixed_json_and_bash(self):
        response = """First read the file:
```json
{"action": "file_read", "params": {"path": "test.py"}}
```
Then run tests:
```bash
pytest
```"""
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, "file_read")
        self.assertEqual(calls[1].name, "bash")

    def test_no_tool_calls(self):
        response = "I think the issue is in the function. Let me explain..."
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 0)

    def test_invalid_json_ignored(self):
        response = "```json\n{invalid json}\n```"
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 0)

    def test_action_or_name(self):
        response = '```json\n{"name": "grep", "arguments": {"pattern": "test"}}\n```'
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "grep")

    def test_raw_nested_json_call(self):
        response = '{"action": "file_edit", "params": {"command": "view", "path": "configs/nexus_config.yaml"}}'
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "file_edit")
        self.assertEqual(calls[0].params["command"], "view")

    def test_top_level_tool_params(self):
        response = '{"action": "glob", "pattern": "**/*.py"}'
        calls = self.loop._extract_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "glob")
        self.assertEqual(calls[0].params["pattern"], "**/*.py")


class TestCompactMemory(unittest.TestCase):
    """Test memory compaction."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())
        self.loop.COMPACT_THRESHOLD = 4
        self.loop.COMPACT_KEEP = 2

    def test_no_compaction_when_under_threshold(self):
        messages = [
            {"role": "system", "content": "You are NEXUS"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = self.loop._compact_memory(messages)
        self.assertEqual(len(result), 3)

    def test_compaction_when_over_threshold(self):
        messages = [
            {"role": "system", "content": "You are NEXUS"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
            {"role": "user", "content": "Q4"},
            {"role": "assistant", "content": "A4"},
            {"role": "user", "content": "Q5"},
            {"role": "assistant", "content": "A5"},
        ]
        result = self.loop._compact_memory(messages)
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["role"], "system")

    def test_system_message_preserved(self):
        messages = [
            {"role": "system", "content": "You are NEXUS"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
            {"role": "user", "content": "Q4"},
            {"role": "assistant", "content": "A4"},
            {"role": "user", "content": "Q5"},
            {"role": "assistant", "content": "A5"},
        ]
        result = self.loop._compact_memory(messages)
        system_msgs = [m for m in result if m["role"] == "system"]
        self.assertGreaterEqual(len(system_msgs), 1)


class TestAbortReset(unittest.TestCase):
    """Test abort and reset functionality."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_abort_sets_flag(self):
        self.loop.abort()
        self.assertTrue(self.loop._abort_flag.is_set())

    def test_reset_clears_flag(self):
        self.loop.abort()
        self.loop.reset()
        self.assertFalse(self.loop._abort_flag.is_set())

    def test_reset_clears_hive_buffer(self):
        self.loop.hive_buffer = ["update1", "update2"]
        self.loop.reset()
        self.assertEqual(len(self.loop.hive_buffer), 0)


class TestNoToolTurnCompletion(unittest.TestCase):
    """Test no-tool responses do not spin through MAX_TURNS."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_plain_response_completes_without_extra_turns(self):
        self.assertFalse(self.loop._should_continue_without_tools("Here is the answer.", 1))

    def test_provider_error_completes_without_retry_spin(self):
        self.assertFalse(self.loop._should_continue_without_tools("[PROVIDER_ERROR]: no key", 1))


class TestObserveHive(unittest.TestCase):
    """Test hive observation."""

    def setUp(self):
        import tempfile
        from orchestrators.loop import NexusLoop

        self.temp_dir = tempfile.mkdtemp()
        self.loop = NexusLoop(self.temp_dir)
        self.hive_logs = os.path.join(self.temp_dir, "logs", "hive")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_hive_logs_dir(self):
        self.loop._observe_hive()
        self.assertEqual(len(self.loop.hive_buffer), 0)

    def test_recent_log_captured(self):
        os.makedirs(self.hive_logs, exist_ok=True)
        log_path = os.path.join(self.hive_logs, "agent1.log")
        with open(log_path, "w") as f:
            f.write("Line 1\nLine 2\nLine 3\n")
        self.loop._observe_hive()
        self.assertEqual(len(self.loop.hive_buffer), 1)
        self.assertIn("agent1.log", self.loop.hive_buffer[0])

    def test_duplicate_updates_ignored(self):
        os.makedirs(self.hive_logs, exist_ok=True)
        log_path = os.path.join(self.hive_logs, "agent2.log")
        with open(log_path, "w") as f:
            f.write("Update A\n")
        self.loop._observe_hive()
        first_len = len(self.loop.hive_buffer)
        self.loop._observe_hive()
        self.assertEqual(len(self.loop.hive_buffer), first_len)


class TestBuildSystemPrompt(unittest.TestCase):
    """Test system prompt building."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_system_prompt_not_empty(self):
        prompt = self.loop._build_system_prompt()
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    def test_system_prompt_contains_identity(self):
        prompt = self.loop._build_system_prompt()
        self.assertIn("NEXUS", prompt)


if __name__ == "__main__":
    unittest.main()
