"""Real unit tests for the rebuilt evolution subsystems.

Each test exercises actual behavior against a temp directory (or the real repo
for the researcher's local evidence scan), so a regression to stub behavior
fails loudly.
"""
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


@pytest.fixture
def repo_root():
    return REPO_ROOT


class TestNexusResearcher:
    """Local evidence gathering must find real on-disk content."""

    def test_research_finds_skills(self, repo_root):
        from evolution.researcher import NexusResearcher

        researcher = NexusResearcher(repo_root)
        out = researcher.research("skills")

        assert out["status"] == "ok"
        assert isinstance(out["findings"], list) and out["findings"]
        assert isinstance(out["sources"], list) and out["sources"]
        assert isinstance(out["summary"], str) and out["summary"]
        assert {"kind", "name", "path", "score", "matched_terms"} <= set(out["findings"][0])

    def test_research_finds_provider_evidence(self, repo_root):
        from evolution.researcher.scripts.researcher import NexusResearcher

        researcher = NexusResearcher(repo_root)
        out = researcher.research("provider")

        assert out["status"] == "ok"
        assert out["findings"], "keyword scan should surface provider-related docs/tools"

    def test_investigate_returns_question(self, repo_root):
        from evolution.researcher.scripts.researcher import NexusResearcher

        researcher = NexusResearcher(repo_root)
        out = researcher.investigate("How do provider routes work?")

        assert out["status"] == "ok"
        assert out["question"] == "How do provider routes work?"
        assert isinstance(out["findings"], list)

    def test_status_is_healthy(self, repo_root):
        from evolution.researcher.scripts.researcher import NexusResearcher

        researcher = NexusResearcher(repo_root)
        status = researcher.status()

        assert status["status"] == "ok"
        assert status["is_stub"] is False
        assert status["llm"] is False


class TestOmniEvolutionKernel:
    """Orchestration runs all real stages and isolates stage failures."""

    def test_evolve_runs_all_stages_without_crash(self, tmp_path):
        from evolution.omni_kernel import OmniEvolutionKernel

        kernel = OmniEvolutionKernel(str(tmp_path))
        out = kernel.evolve()

        assert out["status"] == "ok"
        assert [s["name"] for s in out["stages"]] == ["ledger", "backlog", "memory_forge", "curator"]
        assert out["failed_stages"] == []

    def test_evolve_records_outcome_and_queues_action(self, tmp_path):
        from evolution.omni_kernel import OmniEvolutionKernel

        kernel = OmniEvolutionKernel(str(tmp_path))
        out = kernel.evolve(
            "win",
            {"action": "investigate gap", "title": "cycle_note", "content": "learned X", "score": 0.8},
            reason="real behavior test",
        )

        assert out["status"] == "ok"
        ledger = next(s for s in out["stages"] if s["name"] == "ledger")
        assert ledger["status"] == "ok" and ledger["recorded_outcome"] == "win"
        backlog = next(s for s in out["stages"] if s["name"] == "backlog")
        assert backlog["status"] == "ok" and backlog["queued"] == 1
        memory = next(s for s in out["stages"] if s["name"] == "memory_forge")
        assert memory["status"] == "ok" and memory["forged"] is True

    def test_fault_isolation_keeps_other_stages_ok(self, tmp_path, monkeypatch):
        from evolution.omni_kernel import OmniEvolutionKernel
        import evolution.memory_forge.scripts.forge as forge_module

        def _boom(self, *args, **kwargs):
            raise RuntimeError("forced memory forge failure")

        monkeypatch.setattr(forge_module.MemoryForge, "forge", _boom)

        kernel = OmniEvolutionKernel(str(tmp_path))
        out = kernel.evolve(
            "lose",
            {"title": "t", "content": "c", "action": "fix the gap", "score": 0.1},
            reason="fault isolation test",
        )

        assert out["status"] == "ok"  # evolve() itself must not raise
        memory = next(s for s in out["stages"] if s["name"] == "memory_forge")
        assert memory["status"] == "error"
        assert "RuntimeError" in memory["error"]
        assert out["failed_stages"] == ["memory_forge"]
        # other stages still ran and succeeded
        ledger = next(s for s in out["stages"] if s["name"] == "ledger")
        assert ledger["status"] == "ok" and ledger["recorded_outcome"] == "lose"
        backlog = next(s for s in out["stages"] if s["name"] == "backlog")
        assert backlog["status"] == "ok" and backlog["queued"] == 1
        curator = next(s for s in out["stages"] if s["name"] == "curator")
        assert curator["status"] == "ok"

    def test_status_reports_last_cycle(self, tmp_path):
        from evolution.omni_kernel import OmniEvolutionKernel

        kernel = OmniEvolutionKernel(str(tmp_path))
        kernel.evolve()
        status = kernel.status()

        assert status["status"] == "ok"
        assert status["is_stub"] is False
        assert isinstance(status["stages"], list) and status["stages"]


class TestEnsembleManager:
    """Winner selection must rank by score, not by input order."""

    def test_selects_higher_confidence_winner(self):
        from evolution.ensemble import EnsembleManager

        manager = EnsembleManager(str(os.getcwd()))
        low = {"answer": "short", "model": "m1", "agent": "a1", "confidence": 0.3}
        mid = {"answer": "medium answer", "model": "m3", "agent": "a3", "confidence": 0.6}
        high = {
            "answer": "a longer, evidence-backed answer with references and verification details",
            "model": "m2", "agent": "a2", "confidence": 0.9,
            "evidence": ["source1"], "verified": True,
        }

        selection = manager.select_winner([low, mid, high])

        assert selection["winner"]["model"] == "m2"
        assert selection["score"] >= selection["runner_up"]["score"]
        assert selection["runner_up"]["model"] == "m3"
        assert selection["ensemble_size"] == 3

    def test_empty_input_is_honest_noop(self):
        from evolution.ensemble.scripts.ensemble import EnsembleManager

        manager = EnsembleManager("tmp")
        selection = manager.select_winner([])

        assert selection["winner"] is None
        assert selection["runner_up"] is None
        assert selection["score"] == 0
        assert selection["ensemble_size"] == 0

    def test_run_ensemble_with_candidates_and_history(self):
        from evolution.ensemble.scripts.ensemble import EnsembleManager

        manager = EnsembleManager("tmp")
        result = manager.run_ensemble("problem", candidates=[
            {"answer": "x", "confidence": 0.2},
            {"answer": "y has more substance and evidence", "confidence": 0.8, "evidence": ["src"]},
        ])

        assert result.strategy == "ensemble"
        assert "y" in result.output
        assert result.confidence is not None
        assert manager.get_history() and manager.get_history()[-1] is result


class TestHyperKernel:
    """Health snapshot registry must register, check, and summarize."""

    def test_registers_checks_and_summarizes(self, tmp_path):
        from evolution.hyper_kernel import HyperKernel

        hyper = HyperKernel(str(tmp_path))
        hyper.register_check("kernel", lambda: {"status": "ok", "ok": True})
        hyper.register_check("tools", lambda: True)

        def _broken():
            raise RuntimeError("tools down")

        hyper.register_check("broken", _broken, module="tools")
        checks = hyper.check_all()

        assert checks["kernel"]["ok"] is True
        assert checks["kernel"]["status"] == "ok"
        assert checks["tools"]["ok"] is True
        assert checks["broken"]["status"] == "error"
        assert "RuntimeError" in checks["broken"]["error"]

        summary = hyper.summary()
        assert summary["ok"] == 2
        assert summary["error"] == 1
        names = [m["name"] for m in summary["modules"]]
        assert {"kernel", "tools", "broken"} <= set(names)

    def test_check_failure_does_not_raise(self, tmp_path):
        from evolution.hyper_kernel.scripts.hyper_kernel import HyperKernel

        def _boom():
            raise ValueError("boom")

        hyper = HyperKernel(str(tmp_path))
        hyper.register_check("x", _boom)
        checks = hyper.check_all()  # must not raise

        assert checks["x"]["status"] == "error"

    def test_empty_registry_summary(self, tmp_path):
        from evolution.hyper_kernel.scripts.hyper_kernel import HyperKernel

        hyper = HyperKernel(str(tmp_path))
        summary = hyper.summary()

        assert summary["status"] == "ok"
        assert summary["ok"] == 0
        assert summary["error"] == 0
