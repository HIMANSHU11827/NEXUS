import tempfile
import unittest


class TestAdaptiveMemoryGraph(unittest.TestCase):
    def test_memory_recall_and_contradiction_repair(self):
        from core.cognition.memory_graph import AdaptiveMemoryGraph

        with tempfile.TemporaryDirectory() as tmp:
            graph = AdaptiveMemoryGraph(tmp)
            graph.add("Dashboard upload validation is unsafe", layer="project", confidence=0.4)
            graph.add("Dashboard upload validation is safe after extension checks passed", layer="project", confidence=0.9)
            recalled = graph.recall("dashboard upload validation")
            self.assertTrue(recalled)
            packet = graph.compressed_packet("dashboard upload")
            self.assertTrue(packet["pointers"])


class TestZeroTokenContextEngine(unittest.TestCase):
    def test_context_packets_route_and_dedupe(self):
        from core.cognition.context_engine import ZeroTokenContextEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = ZeroTokenContextEngine(tmp)
            engine.create_packet("RAG fix", "RAG now persists document chunks and metadata")
            engine.create_packet("RAG fix copy", "RAG now persists document chunks and metadata")
            self.assertTrue(engine.route("RAG metadata"))
            self.assertEqual(engine.purge_duplicates(), 1)


class TestSelfImprovementEngine(unittest.TestCase):
    def test_failure_strategy_recommendation(self):
        from core.cognition.self_improvement import SelfImprovementEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = SelfImprovementEngine(tmp)
            engine.learn_from_failure("pytest rag", "retrieval failed", "rebuild index before asserting retrieval")
            recs = engine.recommend("rag retrieval test")
            self.assertTrue(recs)
            self.assertIn("rebuild", recs[0].strategy)


class TestIntentForecaster(unittest.TestCase):
    def test_forecasts_verification_after_code_change(self):
        from core.cognition.intent_forecaster import IntentForecaster

        with tempfile.TemporaryDirectory() as tmp:
            forecasts = IntentForecaster(tmp).forecast(["fix code bug"], {"python_files": 30})
            needs = [f.need for f in forecasts]
            self.assertIn("run targeted regression tests", needs)


class TestSkillForge(unittest.TestCase):
    def test_skill_forge_stores_workflow(self):
        from core.cognition.skill_forge import SkillForge

        with tempfile.TemporaryDirectory() as tmp:
            forge = SkillForge(tmp)
            forge.forge("RAG Regression", "Verify retrieval changes", ["store doc", "query doc", "assert result"])
            self.assertTrue(forge.search("retrieval"))


if __name__ == "__main__":
    unittest.main()
