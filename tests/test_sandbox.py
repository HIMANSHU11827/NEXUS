import os
import tempfile
import unittest


class TestCommandRiskScorer(unittest.TestCase):
    def test_safe_read_command_is_low_risk(self):
        from sandbox.risk import CommandRiskScorer

        assessment = CommandRiskScorer().assess("rg TODO core")
        self.assertFalse(assessment.blocked)
        self.assertEqual(assessment.level, "low")

    def test_recursive_delete_is_blocked(self):
        from sandbox.risk import CommandRiskScorer

        assessment = CommandRiskScorer().assess("rm -rf /")
        self.assertTrue(assessment.blocked)
        self.assertEqual(assessment.level, "critical")


class TestRepoMapBuilder(unittest.TestCase):
    def test_python_symbols_are_indexed_without_importing(self):
        from code_intel.repo_map import RepoMapBuilder

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("import os\nclass Agent:\n    pass\ndef run():\n    return os.getcwd()\n")

            repo_map = RepoMapBuilder(tmp).build()
            self.assertEqual(len(repo_map.files), 1)
            self.assertIn("Agent", repo_map.files[0].symbols)
            self.assertIn("run", repo_map.files[0].symbols)
            self.assertIn("os", repo_map.files[0].imports)


class TestFailureMemory(unittest.TestCase):
    def test_failure_memory_records_jsonl(self):
        from sandbox.failure_memory import FailureMemory

        with tempfile.TemporaryDirectory() as tmp:
            memory = FailureMemory(tmp)
            memory.record("task", "bash", "boom", {"cmd": "bad"})
            records = memory.recent()
            self.assertEqual(records[-1]["tool"], "bash")
            self.assertEqual(records[-1]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
