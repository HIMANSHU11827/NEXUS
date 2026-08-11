from memory import MemoryContext


def test_memory_context_redacts_credentials_at_model_boundary():
    context = MemoryContext(
        session_history="Bearer session-secret-value",
        rag_context="https://example.test/?api_key=sk-memory-secret",
        knowledge_context="Authorization: Bearer another-secret-value",
    )

    rendered = context.as_text()
    assert "session-secret-value" not in rendered
    assert "sk-memory-secret" not in rendered
    assert "another-secret-value" not in rendered
    assert "***REDACTED***" in rendered
