import asyncio
from types import SimpleNamespace

from hive.engine import NexusHiveEngine


def _agent(identifier, persona, result, status="success"):
    return SimpleNamespace(
        agent_id=identifier,
        persona=persona,
        task="vote",
        result=result,
        status=status,
        tool_calls=[],
    )


def test_hive_quorum_accepts_matching_explicit_votes(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_votes"] = [
        _agent("a1", "RESEARCHER", "VOTE: APPROVE\nEvidence A"),
        _agent("a2", "REVIEWER", "VOTE: approve\nEvidence B"),
        _agent("a3", "TESTER", "VOTE: REJECT\nEvidence C"),
    ]

    assessment = engine.assess_quorum("hive_votes", quorum=2, required_personas=["RESEARCHER", "REVIEWER"])

    assert assessment["accepted"] is True
    assert assessment["winning_vote"] == "approve"
    assert len(assessment["votes"]["approve"]) == 2
    assert assessment["missing_personas"] == []


def test_hive_quorum_fails_closed_on_disagreement_and_failure(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_split"] = [
        _agent("a1", "WORKER", "VOTE: A"),
        _agent("a2", "WORKER", "VOTE: B"),
        _agent("a3", "WORKER", "provider failed", status="failed"),
    ]

    assessment = engine.assess_quorum("hive_split", quorum=2)

    assert assessment["accepted"] is False
    assert any("no vote reached quorum" in reason for reason in assessment["reasons"])


def test_require_quorum_prevents_unverified_llm_consolidation(tmp_path):
    async def scenario():
        engine = NexusHiveEngine(str(tmp_path))
        engine._hives["hive_blocked"] = [
            _agent("a1", "WORKER", "VOTE: A"),
            _agent("a2", "WORKER", "VOTE: B"),
        ]
        called = []

        async def llm(_messages):
            called.append(True)
            return "unsafe acceptance"

        result = await engine.consolidate_hive(
            "hive_blocked", timeout=1, llm_call=llm, require_quorum=True, quorum=2,
        )

        assert result.startswith("QUORUM NOT REACHED:")
        assert called == []

    asyncio.run(scenario())


def test_all_failed_hive_fails_closed_without_llm_consolidation(tmp_path):
    async def scenario():
        engine = NexusHiveEngine(str(tmp_path))
        engine._hives["hive_failed"] = [
            _agent("a1", "WORKER", "provider failed", status="failed"),
            _agent("a2", "REVIEWER", "", status="cancelled"),
        ]
        called = []

        async def llm(_messages):
            called.append(True)
            return "hallucinated recovery"

        result = await engine.consolidate_hive("hive_failed", timeout=1, llm_call=llm)

        assert result.startswith("HIVE FAILED:")
        assert "provider failed" in result
        assert called == []

    asyncio.run(scenario())
