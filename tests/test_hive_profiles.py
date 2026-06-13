import os
import tempfile
import unittest


class TestHiveUsesProfiles(unittest.TestCase):
    def test_hive_personas_are_loaded_from_profiles(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as root:
            coder_dir = os.path.join(root, "hive", "profiles", "coder")
            reviewer_dir = os.path.join(root, "hive", "profiles", "reviewer")
            os.makedirs(coder_dir, exist_ok=True)
            os.makedirs(reviewer_dir, exist_ok=True)
            with open(os.path.join(coder_dir, "profile.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "name: coder\n"
                    "description: Coder profile from test.\n"
                    "inherits: base\n"
                )
            with open(os.path.join(reviewer_dir, "profile.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "name: reviewer\n"
                    "description: Reviewer profile from test.\n"
                    "inherits: base\n"
                )

            hive = NexusHiveEngine(root, worker_fn=lambda task, context: "result: ok")

            self.assertEqual(hive.personas["ENGINEER"], "Coder profile from test.")
            self.assertEqual(hive.personas["AUDITOR"], "Reviewer profile from test.")


if __name__ == "__main__":
    unittest.main()

