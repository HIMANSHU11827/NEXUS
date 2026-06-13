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
        compacted = next(m for m in result if "[CONTEXT_COMPACTED]" in m["content"])
        self.assertIn("User goals", compacted["content"])
        self.assertIn("Assistant progress/actions", compacted["content"])
        self.assertIn("Q1", compacted["content"])

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

    def test_compaction_preserves_tool_and_system_observations(self):
        messages = [
            {"role": "system", "content": "You are NEXUS"},
            {"role": "user", "content": "Fix the router and verify tests"},
            {"role": "assistant", "content": "Implemented router fix and verified targeted tests passed."},
            {"role": "tool", "content": "pytest tests/test_unified_loop.py -q passed"},
            {"role": "system", "content": "[AUTO_OBSERVATION]: git diff shows router changes"},
            {"role": "user", "content": "Now improve context compaction"},
            {"role": "assistant", "content": "I will inspect the compaction path."},
            {"role": "user", "content": "Keep recent context too"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "final check"},
            {"role": "assistant", "content": "Checking."},
        ]
        result = self.loop._compact_memory(messages)
        packet = next(m["content"] for m in result if "[CONTEXT_COMPACTED]" in m["content"])
        self.assertIn("Fix the router", packet)
        self.assertIn("Implemented router fix", packet)
        self.assertIn("pytest tests/test_unified_loop.py", packet)
        self.assertIn("AUTO_OBSERVATION", packet)


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


class TestSessionSelfCompaction(unittest.TestCase):
    """Test persistent short-term memory compaction."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_session_memory_uses_compaction_packet(self):
        self.loop.memory = []
        for i in range(11):
            self.loop.memory.append({"role": "user", "content": f"Goal {i}: improve project"})
            self.loop.memory.append({"role": "assistant", "content": f"Progress {i}: verified work"})

        archived_memory = self.loop.memory[:-10]
        self.loop.memory = [
            {
                "role": "system",
                "content": self.loop._summarize_compacted_messages(archived_memory, kept_count=10),
            }
        ] + self.loop.memory[-10:]

        self.assertEqual(len(self.loop.memory), 11)
        self.assertIn("[CONTEXT_COMPACTED]", self.loop.memory[0]["content"])
        self.assertIn("Goal 0", self.loop.memory[0]["content"])
        self.assertIn("Progress", self.loop.memory[0]["content"])

    def test_loop_checkpoint_persists_metadata(self):
        messages = [
            {"role": "system", "content": "You are NEXUS"},
            {"role": "user", "content": "continue this long task"},
        ]
        self.loop.session_id = "checkpoint-test"
        self.loop._checkpoint_loop_session("continue this long task", messages, turn=3, status="running", last_response="working")
        checkpoint = self.loop.persistence.load_checkpoint("checkpoint-test")
        self.assertEqual(checkpoint["turns"], 2)
        self.assertEqual(checkpoint["metadata"]["turn"], 3)
        self.assertEqual(checkpoint["metadata"]["status"], "running")
        self.assertIn("continue this long task", checkpoint["metadata"]["task"])


class TestNoToolTurnCompletion(unittest.TestCase):
    """Test no-tool responses do not spin through MAX_TURNS."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_plain_response_completes_without_extra_turns(self):
        self.assertFalse(self.loop._should_continue_without_tools("Here is the answer.", 1))

    def test_provider_error_completes_without_retry_spin(self):
        self.assertFalse(self.loop._should_continue_without_tools("[PROVIDER_ERROR]: no key", 1))


class TestIntentRouting(unittest.TestCase):
    """Test unified chat/agent routing decisions."""

    def test_social_neural_intent_stays_chat_without_tools(self):
        from router import IntentRouter

        result = IntentRouter().classify("hello there")
        self.assertEqual(result.intent, "chat")
        self.assertFalse(result.needs_tools)
        self.assertEqual(result.tool_hints, [])

    def test_strategy_request_is_understood_without_mode_switching(self):
        from router import IntentRouter

        result = IntentRouter().classify("act like our ceo and make a roadmap to compete in market")
        self.assertEqual(result.intent, "strategy")
        self.assertTrue(result.needs_tools)
        self.assertIn("roadmap", result.tool_hints)


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

    def test_system_prompt_contains_adaptive_collaboration_contract(self):
        prompt = self.loop._build_system_prompt("fix the project and create a roadmap")
        self.assertIn("ADAPTIVE_COLLABORATION", prompt)
        self.assertIn("one continuous NEXUS coworker", prompt)
        self.assertIn("not separate chat/worker/CEO modes", prompt)


class TestHiveDelegationDecisions(unittest.TestCase):
    """Test automatic Hive worker escalation for broad missions."""

    def setUp(self):
        from orchestrators.loop import NexusLoop

        self.loop = NexusLoop(tempfile.mkdtemp())

    def test_small_chat_does_not_delegate_to_hive(self):
        from router import IntentResult

        intent = IntentResult("chat", 0.9, needs_tools=False, complexity="simple")
        self.assertFalse(self.loop._should_delegate_to_hive("hello friend", intent))

    def test_large_project_request_delegates_to_hive(self):
        from router import IntentResult

        intent = IntentResult("strategy", 0.9, needs_tools=True, complexity="medium")
        task = "read full source, understand whole project, fix improve, add tests, roadmap a to z, compete in market"
        self.assertTrue(self.loop._should_delegate_to_hive(task, intent))

    def test_hive_roles_match_mixed_mission(self):
        roles = self.loop._hive_roles_for_task(
            "fix code, verify tests, audit risks, research market",
            "ENGINEER AUDITOR RESEARCHER",
        )
        self.assertIn("ARCHITECT", roles)
        self.assertIn("ENGINEER", roles)
        self.assertIn("QA_EXPERT", roles)
        self.assertIn("AUDITOR", roles)
        self.assertIn("RESEARCHER", roles)
        self.assertEqual(roles[-1], "LIBRARIAN")

    def test_hive_roles_include_dynamic_specialists(self):
        roles = self.loop._hive_roles_for_task(
            "improve gui ux, provider routing, memory context compaction, performance benchmarks, product roadmap",
            "",
        )
        self.assertIn("GUI_UX_SPECIALIST", roles)
        self.assertIn("PROVIDER_ROUTING_SPECIALIST", roles)
        self.assertIn("MEMORY_CONTEXT_ARCHITECT", roles)
        self.assertIn("PERFORMANCE_ENGINEER", roles)
        self.assertIn("PRODUCT_STRATEGIST", roles)


class TestParallelToolExecution(unittest.TestCase):
    """Test parallel tool execution for reads and safe writes."""

    def setUp(self):
        from orchestrators.loop import NexusLoop
        self.loop = NexusLoop(tempfile.mkdtemp())
        self.loop.operator_bypass_mode = True
        self.original_tool_root = self.loop.tool_registry.get("file_edit").root
        self.loop.tool_registry.get("file_edit").root = self.loop.root

    def tearDown(self):
        self.loop.tool_registry.get("file_edit").root = self.original_tool_root

    def test_parallel_independent_file_edits(self):
        from orchestrators.loop import ToolCall
        
        f1 = os.path.join(self.loop.root, "f1.txt")
        f2 = os.path.join(self.loop.root, "f2.txt")
        with open(f1, "w") as f: f.write("f1 content")
        with open(f2, "w") as f: f.write("f2 content")

        calls = [
            ToolCall("file_edit", {"command": "str_replace", "path": "f1.txt", "old_str": "f1 content", "new_str": "f1 updated"}),
            ToolCall("file_edit", {"command": "str_replace", "path": "f2.txt", "old_str": "f2 content", "new_str": "f2 updated"}),
        ]
        
        observations = self.loop._execute_tools(calls)
        self.assertEqual(len(observations), 2)
        
        with open(f1, "r") as f:
            self.assertEqual(f.read(), "f1 updated")
        with open(f2, "r") as f:
            self.assertEqual(f.read(), "f2 updated")

    def test_sequential_dependent_file_edits(self):
        from orchestrators.loop import ToolCall
        
        f1 = os.path.join(self.loop.root, "f1.txt")
        with open(f1, "w") as f: f.write("original")

        calls = [
            ToolCall("file_edit", {"command": "str_replace", "path": "f1.txt", "old_str": "original", "new_str": "step1"}),
            ToolCall("file_edit", {"command": "str_replace", "path": "f1.txt", "old_str": "step1", "new_str": "step2"}),
        ]
        
        observations = self.loop._execute_tools(calls)
        self.assertEqual(len(observations), 2)
        
        with open(f1, "r") as f:
            self.assertEqual(f.read(), "step2")

    def test_parallel_concurrency_safe_non_file_writes(self):
        import time
        from orchestrators.loop import ToolCall
        from tools.nexus_tools.base_tool import BaseTool, ToolResult
        
        class MockSafeWriteTool(BaseTool):
            name = "mock_safe_write"
            
            def __init__(self):
                self.calls = []
                
            def call(self, val: str = "") -> ToolResult:
                self.calls.append(val)
                time.sleep(0.02)
                return ToolResult(data=f"written: {val}")

            def is_concurrency_safe(self, input_data=None):
                return True

            def is_read_only(self, input_data=None):
                return False

        mock_tool = MockSafeWriteTool()
        self.loop.tool_registry.register(mock_tool)
        
        calls = [
            ToolCall("mock_safe_write", {"val": "a"}),
            ToolCall("mock_safe_write", {"val": "b"}),
        ]
        
        observations = self.loop._execute_tools(calls)
        self.assertEqual(len(observations), 2)
        self.assertIn("[mock_safe_write]: written: a", observations)
        self.assertIn("[mock_safe_write]: written: b", observations)
        self.assertEqual(len(mock_tool.calls), 2)

    def test_plan_act_posture_separation(self):
        from orchestrators.loop import ToolCall
        from tools.nexus_tools.base_tool import BaseTool, ToolResult
        
        class MockWriteTool(BaseTool):
            name = "mock_write_separate"
            def call(self, val: str = "") -> ToolResult:
                return ToolResult(data=f"done: {val}")
            def is_read_only(self, input_data=None):
                return False

        mock_tool = MockWriteTool()
        self.loop.tool_registry.register(mock_tool)
        
        # 1. Enforced planning phase (Write blocked)
        self.loop.in_planning_phase = True
        calls = [ToolCall("mock_write_separate", {"val": "hello"})]
        observations = self.loop._execute_tools(calls)
        self.assertEqual(len(observations), 1)
        self.assertIn("[PLANNING_PHASE_RESTRICTION]", observations[0])
        
        # 2. Acting phase (Write permitted)
        self.loop.in_planning_phase = False
        observations = self.loop._execute_tools(calls)
        self.assertEqual(len(observations), 1)
        self.assertIn("[mock_write_separate]: done: hello", observations[0])


if __name__ == "__main__":
    unittest.main()
