import os
import tempfile
import unittest


class TestSecretScanner(unittest.TestCase):
    def test_detects_committed_keys_but_allows_env_placeholders(self):
        from core.security.secret_scanner import SecretScanner

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "config.yaml"), "w", encoding="utf-8") as f:
                f.write("api_key: ${OPENROUTER_API_KEY}\n")
            with open(os.path.join(tmp, "bad.yaml"), "w", encoding="utf-8") as f:
                f.write("api_key: " + "sk-or-v1-" + "thisisaverylongbadcommittedsecret" + "\n")
            findings = SecretScanner(tmp).scan()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "bad.yaml")

    def test_repository_has_no_obvious_committed_api_keys(self):
        from core.security.secret_scanner import SecretScanner

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        findings = SecretScanner(root).scan(["configs", "core", "tools", "dashboard", "tests", "docs", "README.md"])
        self.assertEqual([], findings)

    def test_system_audit_uses_secret_scanner(self):
        from tools.nexus_tools.system_audit import SystemAuditorTool

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bad.yaml"), "w", encoding="utf-8") as f:
                f.write("api_key: " + "sk-or-v1-" + "thisisaverylongbadcommittedsecret" + "\n")
            result = SystemAuditorTool(tmp).call(".")
        self.assertTrue(result.success)
        self.assertIn("[SECRET_FOUND]", str(result))


if __name__ == "__main__":
    unittest.main()
