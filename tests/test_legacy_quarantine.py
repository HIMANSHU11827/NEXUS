import os
import re
import unittest


class TestLegacyToolQuarantine(unittest.TestCase):
    def test_active_python_code_does_not_import_legacy_tool_folders(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pattern = re.compile(
            r"(?:from|import)\s+tools\.(terminal|file_ops|tester|git|docker|elite)\b"
            r"|tools\.(terminal|file_ops|tester|git|docker|elite)\.script"
        )
        offenders = []
        for base in ["core", "orchestrators", "tools", "rag", "tests"]:
            base_path = os.path.join(root, base)
            for dirpath, dirnames, filenames in os.walk(base_path):
                dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules"}]
                for filename in filenames:
                    if filename.endswith(".py"):
                        path = os.path.join(dirpath, filename)
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if pattern.search(content):
                            offenders.append(os.path.relpath(path, root).replace("\\", "/"))
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
