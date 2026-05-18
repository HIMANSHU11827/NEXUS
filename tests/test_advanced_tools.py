import json
import os
import tempfile
import time
import unittest


class TestAdvancedToolsViaRegistry(unittest.TestCase):
    def setUp(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = ToolRegistry()
        # Rebuild the registry against the temp root for file-sensitive tools.
        self.registry._tools = {}
        self.registry._initialized = True
        from tools.nexus_tools.advanced_power_tool import (
            BenchmarkTool,
            BrowserAutomationTool,
            CognitionTool,
            HyperPlanTool,
            MissionReplayTool,
            PatchLedgerTool,
            ProcessTool,
            RollbackTool,
            SideEffectTool,
            SkillForgeTool,
            ToolEconomyTool,
        )

        for tool in [
            RollbackTool(self.tmp.name),
            PatchLedgerTool(self.tmp.name),
            ProcessTool(self.tmp.name),
            SideEffectTool(self.tmp.name),
            HyperPlanTool(),
            CognitionTool(self.tmp.name),
            SkillForgeTool(self.tmp.name),
            BenchmarkTool(self.tmp.name),
            MissionReplayTool(self.tmp.name),
            ToolEconomyTool(self.tmp.name),
            BrowserAutomationTool(self.tmp.name),
        ]:
            self.registry.register(tool)
        self.registry.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_hyper_plan_tool(self):
        out = self.registry.execute("hyper_plan", task="fix api bug and run tests")
        data = json.loads(out)
        self.assertIn("steps", data)
        self.assertGreater(data["uncertainty"], 0)

    def test_rollback_tool(self):
        path = os.path.join(self.tmp.name, "file.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("before")
        out = self.registry.execute("rollback", command="snapshot", paths=["file.txt"], reason="test")
        snap = json.loads(out)
        with open(path, "w", encoding="utf-8") as f:
            f.write("after")
        restored = self.registry.execute("rollback", command="restore", snapshot_id=snap["id"])
        self.assertIn("Restored 1", restored)
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "before")

    def test_cognition_and_skill_forge_tools(self):
        remembered = self.registry.execute("cognition", command="remember", text="Rollback should snapshot before risky edits")
        self.assertIn("Rollback", remembered)
        recalled = self.registry.execute("cognition", command="recall", query="risky edits")
        self.assertIn("snapshot", recalled)
        forged = self.registry.execute(
            "skill_forge",
            command="forge",
            name="Safe Edit",
            description="Snapshot then edit then test",
            steps=["snapshot files", "edit", "run tests"],
        )
        self.assertIn("Safe Edit", forged)

    def test_process_tool(self):
        started = self.registry.execute("process", command="start", cmd="python -c \"print('ok')\"", compress=False)
        data = json.loads(started)
        deadline = time.time() + 5
        polled = {}
        while time.time() < deadline:
            polled = json.loads(self.registry.execute("process", command="poll", process_id=data["id"], use_cache=False, compress=False))
            if polled.get("returncode") is not None:
                break
            time.sleep(0.05)
        self.assertEqual(polled.get("returncode"), 0)

    def test_process_tool_blocks_dangerous_background_commands(self):
        out = self.registry.execute("process", command="start", cmd="rm -rf /", compress=False)
        self.assertIn("Blocked unsafe background command", out)

    def test_patch_ledger_tool_records_diff(self):
        path = os.path.join(self.tmp.name, "ledger.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("before\n")
        baseline = json.loads(self.registry.execute("patch_ledger", command="baseline", paths=["ledger.txt"], reason="test", compress=False))
        with open(path, "w", encoding="utf-8") as f:
            f.write("after\n")
        record = json.loads(
            self.registry.execute(
                "patch_ledger",
                command="record",
                baseline_id=baseline["id"],
                paths=["ledger.txt"],
                reason="changed",
                compress=False,
            )
        )
        self.assertIn("-before", record["files"][0]["diff"])
        self.assertIn("+after", record["files"][0]["diff"])

    def test_benchmark_history_tool(self):
        out = self.registry.execute("benchmark", command="history", compress=False)
        self.assertEqual(json.loads(out), [])

    def test_benchmark_runner_records_suite_version(self):
        from core.evaluation.benchmark import BenchmarkRunner

        result = BenchmarkRunner(self.tmp.name).run(cases=[])
        self.assertIn("suite_version", result)

    def test_mission_replay_and_tool_economy_record_tool_calls(self):
        out = self.registry.execute("hyper_plan", task="fix api bug and run tests", compress=False)
        self.assertIn("steps", out)
        replay = json.loads(self.registry.execute("mission_replay", command="recent", compress=False))
        self.assertTrue(any(event["data"].get("tool") == "hyper_plan" for event in replay))
        market = json.loads(self.registry.execute("tool_economy", command="rank", compress=False))
        self.assertTrue(any(item["tool"] == "hyper_plan" and item["success_rate"] == 1.0 for item in market))

    def test_browser_tool_reports_status_and_fetches_static_pages(self):
        status = json.loads(self.registry.execute("browser", command="status", compress=False))
        self.assertIn("playwright_available", status)
        fetched = json.loads(
            self.registry.execute(
                "browser",
                command="fetch",
                url="https://example.com",
                max_chars=100,
                compress=False,
            )
        )
        self.assertEqual(fetched["status_code"], 200)
        self.assertIn("Example Domain", fetched["text"])

    def test_browser_tool_is_honest_when_playwright_missing(self):
        out = json.loads(self.registry.execute("browser", command="run_sequence", url="https://example.com", compress=False))
        if not out.get("ok"):
            self.assertIn("Playwright not installed", out["error"])


class TestFileEditAutoRollback(unittest.TestCase):
    def test_file_edit_creates_rollback_snapshot_before_replace(self):
        from tools.nexus_tools.file_edit_tool import FileEditTool

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("before")
            result = FileEditTool(tmp).call(command="str_replace", path="a.txt", old_str="before", new_str="after")
            self.assertTrue(result.success)
            self.assertIn("ROLLBACK_SNAPSHOT", str(result))
            self.assertIn("PATCH_LEDGER", str(result))

    def test_file_edit_blocks_directory_delete_by_default(self):
        from tools.nexus_tools.file_edit_tool import FileEditTool

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "delete_dir")
            os.makedirs(target, exist_ok=True)
            result = FileEditTool(tmp).call(command="delete", path=target)
            self.assertFalse(result.success)
            self.assertTrue(os.path.isdir(target))
            self.assertIn("Refusing recursive directory delete", str(result))


if __name__ == "__main__":
    unittest.main()
