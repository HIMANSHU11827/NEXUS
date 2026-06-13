import json
import os
import tempfile
import unittest


class TestEvolutionContextMap(unittest.TestCase):
    def test_context_map_indexes_evolution_surfaces(self):
        from evolution.context import EvolutionContextMap

        with tempfile.TemporaryDirectory() as root:
            for path in [
                "skill/demo/SKILL.md",
                "plugins/sample/SKILL.md",
                "hive/profiles/default/profile.yaml",
                "knowledge/_rag_index.json",
                "workspace/evidence_ledger.json",
                "hive/engine.py",
                "core/intelligence/moa.py",
                "evolution/omni_kernel.py",
                "evolution/hyper_kernel.py",
                "optimization/evidence_ledger.py",
            ]:
                full = os.path.join(root, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    if path.endswith(".json"):
                        json.dump({}, f)
                    else:
                        f.write("name: default\ndescription: test\n")

            context = EvolutionContextMap(root).build()

            self.assertTrue(context["surfaces"]["skills"]["present"])
            self.assertEqual(context["surfaces"]["plugins"]["count"], 1)
            self.assertTrue(context["surfaces"]["profiles"]["present"])
            self.assertTrue(context["surfaces"]["rag"]["present"])
            self.assertGreaterEqual(context["surfaces"]["consensus"]["count"], 3)

    def test_nexus_evolve_context_mode_returns_json(self):
        from tools.nexus_tools.nexus_evolve_tool import NexusEvolveTool

        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "plugins"), exist_ok=True)
            result = NexusEvolveTool(root).call(mode="context")

            self.assertTrue(result.success)
            data = json.loads(result.data)
            self.assertIn("surfaces", data)
            self.assertIn("plugins", data["surfaces"])


if __name__ == "__main__":
    unittest.main()

