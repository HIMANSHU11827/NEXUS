__version__ = "1.0.0"

import json
import os

import pytest

from memory import MemoryContext, MemoryManager


class TestMemoryContext:
    def test_empty_as_text(self):
        ctx = MemoryContext()
        assert ctx.as_text() == ""

    def test_as_text_with_session(self):
        ctx = MemoryContext(session_history="user: hello")
        text = ctx.as_text()
        assert "[SESSION]" in text
        assert "user: hello" in text

    def test_as_text_with_all_fields(self):
        ctx = MemoryContext(
            session_history="sess",
            rag_context="rag",
            failure_vaccines="fail",
            knowledge_context="know",
        )
        text = ctx.as_text()
        for tag in ("[SESSION]", "[RAG]", "[FAILURES]", "[KNOWLEDGE]"):
            assert tag in text


class TestMemoryManager:
    @pytest.fixture
    def tmp_root(self, tmp_path):
        return str(tmp_path)

    @pytest.fixture
    def mm(self, tmp_root):
        m = MemoryManager(tmp_root, session_id="test_sesh", max_session_lines=4)
        yield m
        m.shutdown()

    def test_init_creates_dirs(self, mm):
        assert os.path.isdir(mm.root)

    def test_set_get(self, mm):
        mm.set("episodic", "I learned Python")
        assert mm.get("episodic") == "I learned Python"

    def test_get_default(self, mm):
        assert mm.get("nonexistent") == ""

    def test_set_get_default(self, mm):
        assert mm.get("nonexistent", "fallback") == "fallback"

    def test_summary_empty(self):
        mm = MemoryManager("/tmp/_nexus_test_empty", session_id="empty")
        mm.shutdown()
        assert mm.summary() == ""

    def test_summary_with_values(self, mm):
        mm.set("episodic", "Hello world this is a long value that should be trimmed")
        mm.set("working", "Active task")
        s = mm.summary()
        assert "episodic:" in s
        assert "working:" in s
        assert "Active task" in s

    def test_prefetch_session_loads_file(self, mm):
        sesh_dir = os.path.join(mm.root, "logs", "sessions")
        os.makedirs(sesh_dir, exist_ok=True)
        path = os.path.join(sesh_dir, "test_sesh.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ], f)
        import asyncio
        ctx = asyncio.run(mm.prefetch_all("hello"))
        assert "USER: hello" in ctx.session_history
        assert "ASSISTANT: hi there" in ctx.session_history

    def test_sync_session_writes_file(self, mm):
        import asyncio
        asyncio.run(mm.sync_all("test user message", "test response"))
        sesh_path = os.path.join(mm.root, "logs", "sessions", "test_sesh.json")
        assert os.path.isfile(sesh_path)
        with open(sesh_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_sync_empty_does_nothing(self, mm):
        import asyncio
        asyncio.run(mm.sync_all("", ""))
        sesh_path = os.path.join(mm.root, "logs", "sessions", "test_sesh.json")
        assert not os.path.isfile(sesh_path)

    def test_prefetch_rag_returns_string(self, mm):
        import asyncio
        ctx = asyncio.run(mm.prefetch_all("test"))
        assert isinstance(ctx.rag_context, str)

    def test_prefetch_failures_handles_no_module(self, mm):
        import asyncio
        ctx = asyncio.run(mm.prefetch_all("test"))
        assert ctx.failure_vaccines == ""
