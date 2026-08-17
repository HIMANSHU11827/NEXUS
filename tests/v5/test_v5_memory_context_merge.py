from types import SimpleNamespace

import pytest

from nexus.main_agent.core import NexusLoopV5


def test_memory_prefetch_enriches_existing_execution_context_without_replacing_it():
    context = "PERCEPTION: intent=diagnostic\nPLAN: inspect the failing test"
    memory = SimpleNamespace(
        session_history="[SESSION]\nprevious evidence",
        rag_context="[RAG]\nrelevant repository context",
        failure_vaccines="[FAILURES]\navoid the known retry loop",
        knowledge_context="[KNOWLEDGE]\nproject convention",
        episodic="[EPISODIC]\nprior repair",
        procedural="[PROCEDURAL]\nrun the focused test",
    )

    merged = NexusLoopV5._merge_memory_context(context, memory)

    assert "PERCEPTION: intent=diagnostic" in merged
    assert "PLAN: inspect the failing test" in merged
    assert "[FAILURES]" in merged
    assert "[PROCEDURAL]" in merged


@pytest.mark.asyncio
async def test_perception_injects_all_memory_channels_before_planning():
    from nexus.main_agent.core import NexusLoopV5, V5TurnContext

    memory = SimpleNamespace(
        session_history="[SESSION] previous",
        rag_context="[RAG] relevant",
        failure_vaccines="[FAILURES] avoid retry loop",
        knowledge_context="[KNOWLEDGE] repository convention",
        episodic="[EPISODIC] prior repair",
        working="[WORKING] open task",
        semantic="[SEMANTIC] domain fact",
        procedural="[PROCEDURAL] run focused test",
    )

    class Memory:
        async def prefetch_all(self, _message):
            return memory

    loop = NexusLoopV5.__new__(NexusLoopV5)
    loop._perception = None
    loop._memory_manager = Memory()
    turn = V5TurnContext(
        turn_id="memory-turn",
        session_id="memory-session",
        user_input="continue the repair",
        input_type="text",
    )

    perceived = await loop._perceive_input(turn)
    for marker in (
        "[SESSION]", "[RAG]", "[FAILURES]", "[KNOWLEDGE]", "[EPISODIC]",
        "[WORKING]", "[SEMANTIC]", "[PROCEDURAL]",
    ):
        assert marker in perceived.context_summary
    assert turn.metadata["_memory_context"] is memory


def test_bounded_memory_recall_prevents_large_session_from_starving_procedural_context():
    from nexus.main_agent.core import NexusLoopV5

    memory = SimpleNamespace(
        session_history="[SESSION]" + "s" * 10000,
        rag_context="[RAG]" + "r" * 5000,
        procedural="[PROCEDURAL] run the recovery checklist",
    )
    recall = NexusLoopV5._bounded_memory_recall(memory)

    assert len(recall) <= 8000
    assert "[SESSION]" in recall
    assert "[RAG]" in recall
    assert "[PROCEDURAL] run the recovery checklist" in recall


def test_memory_merge_does_not_duplicate_recall_reused_by_direct_loop():
    memory = SimpleNamespace(
        session_history="prior evidence",
        procedural="run the focused test",
    )

    perceived_context = NexusLoopV5._merge_memory_context("request", memory)
    direct_context = NexusLoopV5._merge_memory_context(perceived_context, memory)

    assert direct_context == perceived_context
    assert direct_context.count("[RECALL]") == 1


def test_bounded_memory_recall_redacts_secrets_before_model_context():
    memory = SimpleNamespace(
        session_history="Authorization: Bearer session-secret-value",
        procedural="use api_key=sk-procedural-secret",
    )

    recall = NexusLoopV5._bounded_memory_recall(memory)

    assert "session-secret-value" not in recall
    assert "sk-procedural-secret" not in recall
    assert "***REDACTED***" in recall
