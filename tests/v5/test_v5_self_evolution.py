import asyncio
from types import SimpleNamespace

from nexus.main_agent.self_evolution import EvolutionCandidate, SelfEvolutionLayer


def test_unsafe_self_evolution_does_not_claim_failed_deployment(tmp_path, monkeypatch):
    layer = SelfEvolutionLayer(str(tmp_path))
    layer.safe_mode = False
    candidate = EvolutionCandidate(
        candidate_id="candidate-failed",
        description="failed write",
        code_changes={"config.json": "{}"},
        confidence=1.0,
    )
    rollback_calls = []

    async def analyze(_runtime):
        return {"ok": True}

    async def generate(_analysis):
        return [candidate]

    async def test_candidates(candidates):
        return candidates

    async def deploy(_candidate):
        return False

    async def rollback(_candidate):
        rollback_calls.append(True)

    monkeypatch.setattr(layer, "_analyze_system", analyze)
    monkeypatch.setattr(layer, "_generate_improvements", generate)
    monkeypatch.setattr(layer, "_test_candidates", test_candidates)
    monkeypatch.setattr(layer, "_deploy_candidate", deploy)
    monkeypatch.setattr(layer, "_rollback", rollback)

    runtime = SimpleNamespace(
        turn_history=[],
        meta_learning_enabled=False,
        quantum_mode=False,
        consciousness_level=0,
        swarm_size=0,
    )
    result = asyncio.run(layer.evolve(runtime))

    assert result["success"] is False
    assert result["deployed"] is None
    assert result["rollback"] is True
    assert rollback_calls == [True]


def test_multi_file_deployment_rolls_back_after_atomic_replace_failure(tmp_path, monkeypatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    layer = SelfEvolutionLayer(str(tmp_path))
    candidate = EvolutionCandidate(
        candidate_id="candidate-partial",
        description="partial failure",
        code_changes={
            "first.txt": "new-first",
            "second.txt": "new-second",
            "new.txt": "new-file",
        },
        confidence=1.0,
    )
    original_replace = __import__(
        "nexus.main_agent.self_evolution", fromlist=["os"]
    ).os.replace
    calls = 0

    def fail_on_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated commit failure")
        return original_replace(source, target)

    monkeypatch.setattr(
        "nexus.main_agent.self_evolution.os.replace", fail_on_second_replace
    )
    deployed = asyncio.run(layer._deploy_candidate(candidate))

    assert deployed is False
    assert first.read_text(encoding="utf-8") == "old-first"
    assert second.read_text(encoding="utf-8") == "old-second"
    assert not (tmp_path / "new.txt").exists()
    assert not layer._deployed_backups


def test_new_layer_recovers_interrupted_transaction_manifest(tmp_path):
    existing = tmp_path / "existing.txt"
    backup = tmp_path / "existing.txt.bak"
    created = tmp_path / "created.txt"
    existing.write_text("partial-new", encoding="utf-8")
    backup.write_text("old-existing", encoding="utf-8")
    created.write_text("partial-created", encoding="utf-8")
    manifest = tmp_path / ".nexus_v5_evolution_transaction.json"
    manifest.write_text(
        __import__("json").dumps({
            "version": 1,
            "status": "commit_started",
            "candidate_id": "crashed",
            "files": [
                {"target": str(existing), "backup": str(backup), "temporary": ""},
                {"target": str(created), "backup": None, "temporary": ""},
            ],
        }),
        encoding="utf-8",
    )

    SelfEvolutionLayer(str(tmp_path))

    assert existing.read_text(encoding="utf-8") == "old-existing"
    assert not created.exists()
    assert not manifest.exists()


def test_successful_deployment_removes_transaction_backups(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"old": true}', encoding="utf-8")
    layer = SelfEvolutionLayer(str(tmp_path))
    candidate = EvolutionCandidate(
        candidate_id="candidate-success",
        description="successful write",
        code_changes={"config.json": '{"new": true}'},
        confidence=1.0,
    )

    assert asyncio.run(layer._deploy_candidate(candidate)) is True
    assert target.read_text(encoding="utf-8") == '{"new": true}'
    assert not list(tmp_path.glob("*.bak"))
    assert not list(tmp_path.glob(".nexus-evolution-backup-*.bak"))
    assert not (tmp_path / ".nexus_v5_evolution_transaction.json").exists()
    assert not layer._deployed_backups


def test_committed_transaction_recovery_removes_owned_backups(tmp_path):
    target = tmp_path / "config.json"
    backup = tmp_path / ".nexus-evolution-backup-owned.bak"
    target.write_text('{"new": true}', encoding="utf-8")
    backup.write_text('{"old": true}', encoding="utf-8")
    manifest = tmp_path / ".nexus_v5_evolution_transaction.json"
    manifest.write_text(
        __import__("json").dumps({
            "version": 1,
            "status": "committed",
            "candidate_id": "committed",
            "files": [{"target": str(target), "backup": str(backup), "temporary": ""}],
        }),
        encoding="utf-8",
    )

    SelfEvolutionLayer(str(tmp_path))

    assert target.read_text(encoding="utf-8") == '{"new": true}'
    assert not backup.exists()
    assert not manifest.exists()


def test_closed_evolution_loop_surfaces_backlog_into_context(tmp_path, monkeypatch):
    """Closed-loop proof: the self-improvement backlog (written by
    _evolve_self_improve / _evolve_gap_forge) was write-only -- no live
    runtime ever read it back, so Nexus recorded how to improve but never
    applied it. This test pins the read-half closed: a pending backlog
    action must be surfaced as a [SELF-EVOLUTION] block in the next turn's
    context_summary AND marked 'proposed' so it is not re-proposed on
    every future session."""
    from nexus.main_agent.core import NexusLoopV5
    from evolution.backlog import (
        queue_improvement_action, pending_actions, mark_action_status
    )

    # Seed the evolution write-half (the part that already worked).
    queued = queue_improvement_action(
        {"action": "Cache provider routing decisions across turns",
         "source": "self_improvement.analyze_session"},
        str(tmp_path),
    )
    assert queued is not None
    assert len(pending_actions(str(tmp_path))) == 1

    loop = NexusLoopV5(str(tmp_path), session_id="evolve-closed-loop")
    captured = {}

    async def fake_tool_loop(task_desc, **kwargs):
        captured["context_summary"] = kwargs.get("context_summary", "")
        return {"success": True, "response": "done", "calls_executed": 0,
                "actions": [], "verification": {"success": True}}

    loop._run_direct_model_tool_loop = fake_tool_loop
    # Provide a fake memory manager so the context-assembly block
    # (where the [SELF-EVOLUTION] injection lives) actually runs.
    from types import SimpleNamespace
    loop._memory_manager = SimpleNamespace(
        prefetch_all=lambda _: SimpleNamespace(
            session_history="", rag_context="", failure_vaccines="",
            knowledge_context="", episodic="", procedural=""),
    )

    async def run():
        events = [
            e async for e in loop._turn_events(
                "continue the optimization work", provider="stub",
            )
        ]
        return events

    asyncio.run(run())

    summary = captured.get("context_summary", "")
    assert "[SELF-EVOLUTION]" in summary, summary
    assert "Cache provider routing decisions across turns" in summary
    # Marked in_progress so the same action is not re-proposed next session.
    assert pending_actions(str(tmp_path)) == []  # no longer pending
    from evolution.backlog import read_backlog
    rows = read_backlog(str(tmp_path))
    assert rows and rows[0].get("status") == "in_progress", rows
