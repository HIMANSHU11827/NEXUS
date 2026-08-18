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
            working="work",
        )
        text = ctx.as_text()
        for tag in ("[SESSION]", "[RAG]", "[FAILURES]", "[KNOWLEDGE]", "[WORKING]"):
            assert tag in text

    def test_import_memory_restores_session_history(self):
        manager = MemoryManager(".", session_id="import-test")
        try:
            assert manager.import_memory(json.dumps({
                "session_history": [{"role": "user", "content": "hello"}],
            })) is True
            assert manager._memory == [{"role": "user", "content": "hello"}]
        finally:
            manager.shutdown()


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
        sesh_dir = os.path.join(mm.root, ".nexus", "logs", "sessions")
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
        sesh_path = os.path.join(mm.root, ".nexus", "logs", "sessions", "test_sesh.json")
        assert os.path.isfile(sesh_path)
        with open(sesh_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_concurrent_session_syncs_merge_and_replace_atomically(self, tmp_path):
        import asyncio
        first = MemoryManager(str(tmp_path), session_id="concurrent", max_session_lines=8)
        second = MemoryManager(str(tmp_path), session_id="concurrent", max_session_lines=8)

        async def run():
            await asyncio.gather(
                first.sync_all("first user", "first response"),
                second.sync_all("second user", "second response"),
            )

        asyncio.run(run())
        path = tmp_path / ".nexus" / "logs" / "sessions" / "concurrent.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        contents = {item.get("content") for item in data}
        assert {"first user", "first response", "second user", "second response"} <= contents
        first.shutdown()
        second.shutdown()

    def test_sync_empty_does_nothing(self, mm):
        import asyncio
        asyncio.run(mm.sync_all("", ""))
        sesh_path = os.path.join(mm.root, ".nexus", "logs", "sessions", "test_sesh.json")
        assert not os.path.isfile(sesh_path)

    def test_prefetch_rag_returns_string(self, mm):
        import asyncio
        ctx = asyncio.run(mm.prefetch_all("test"))
        assert isinstance(ctx.rag_context, str)

    def test_prefetch_failures_handles_no_module(self, mm):
        import asyncio
        ctx = asyncio.run(mm.prefetch_all("test"))
        assert ctx.failure_vaccines == ""


class TestVerifiedMemoryGate:
    """Verified-results gate: unverified model prose is never stored as fact."""

    @pytest.fixture
    def mm(self, tmp_path):
        m = MemoryManager(str(tmp_path), session_id="gate_sesh", max_session_lines=8)
        yield m
        m.shutdown()

    def _learned_file(self, mm):
        path = os.path.join(mm._opencode_memory_dir, "learned.md")
        os.makedirs(mm._opencode_memory_dir, exist_ok=True)
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("seed\n")
        return path

    def _session_file(self, mm):
        return os.path.join(mm.root, ".nexus", "logs", "sessions", "gate_sesh.json")

    def test_sync_all_unverified_tags_transcript_and_writes_no_learnings(self, mm):
        import asyncio
        learned = self._learned_file(mm)
        asyncio.run(mm.sync_all("user asks", "a long unverified model claim"))
        # Transcript records the assistant turn but tags it unverified
        with open(self._session_file(mm), encoding="utf-8") as f:
            data = json.load(f)
        assert any(
            m.get("role") == "assistant" and m.get("verified") is False
            for m in data
        )
        # No cross-session learning or forge memory may be written
        assert open(learned, encoding="utf-8").read().strip() == "seed"
        forge_dir = os.path.join(mm.root, "data", "memory_forge")
        assert not os.path.isdir(forge_dir) or not os.listdir(forge_dir)

    def test_sync_all_verified_persists_tool_evidence(self, mm):
        import asyncio
        learned = self._learned_file(mm)
        verified_actions = [
            {"tool": "bash", "output": "42", "success": True, "verified": True},
        ]
        tool_results = [
            {"tool": "bash", "output": "42", "error": "", "success": True},
        ]
        asyncio.run(mm.sync_all(
            "user asks",
            "a long response",
            verified_actions=verified_actions,
            tool_results=tool_results,
        ))
        # .opencode/memory/learned.md got the real tool output, not model prose
        learned_text = open(learned, encoding="utf-8").read()
        assert "bash: 42" in learned_text
        # MemoryForge stored the verified evidence
        mem_dir = os.path.join(mm.root, "data", "memory_forge", "session_gate_sesh")
        assert os.path.isfile(os.path.join(mem_dir, "memory.json"))
        with open(os.path.join(mem_dir, "memory.json"), encoding="utf-8") as f:
            forged = json.load(f)
        assert "bash: 42" in forged["content"]
        assert "a long response" not in forged["content"]

    def test_sync_all_failed_action_writes_no_learnings(self, mm):
        import asyncio
        learned = self._learned_file(mm)
        verified_actions = [
            {"tool": "bash", "success": False, "error": "boom", "verified": False},
        ]
        tool_results = [
            {"tool": "bash", "output": "", "error": "boom", "success": False},
        ]
        asyncio.run(mm.sync_all(
            "user asks",
            "a long response",
            verified_actions=verified_actions,
            tool_results=tool_results,
        ))
        assert open(learned, encoding="utf-8").read().strip() == "seed"
        forge_dir = os.path.join(mm.root, "data", "memory_forge")
        assert not os.path.isdir(forge_dir) or not os.listdir(forge_dir)

    def test_sync_all_persists_redacted_tool_provenance_once(self, mm):
        import asyncio
        learned = self._learned_file(mm)
        tool_results = [{
            "tool": "terminal",
            "call_id": "call-7",
            "output": "Bearer super-secret-value; result=ok",
            "success": True,
        }]
        provenance = {
            "session_id": "gate_sesh",
            "turn_id": "turn-7",
            "task_id": "task-7",
            "provider_run_evidence_path": "C:/workspace/provider_run_evidence/openai/gpt/turn-7.json",
        }
        for _ in range(2):
            asyncio.run(mm.sync_all(
                "user asks", "response", verified_actions=[{"verified": True}],
                tool_results=tool_results, provenance=provenance,
            ))
        evidence_path = os.path.join(mm.root, ".nexus", "v5", "memory_evidence.jsonl")
        with open(evidence_path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) == 1
        record = records[0]
        assert record["provenance"]["turn_id"] == "turn-7"
        assert record["call_id"] == "call-7"
        assert "super-secret-value" not in json.dumps(record)
        learned_text = open(learned, encoding="utf-8").read()
        assert learned_text.count(record["memory_id"]) == 1

    def test_prefetch_session_skips_unverified_assistant_claims(self, mm):
        import asyncio
        os.makedirs(os.path.join(mm.root, ".nexus", "logs", "sessions"), exist_ok=True)
        with open(self._session_file(mm), "w", encoding="utf-8") as f:
            json.dump([
                {"role": "user", "content": "first q"},
                {"role": "assistant", "content": "UNVERIFIED_HALLUCINATION", "verified": False},
                {"role": "user", "content": "second q"},
                {"role": "assistant", "content": "grounded answer", "verified": True},
            ], f)
        ctx = asyncio.run(mm.prefetch_all("second q"))
        assert "UNVERIFIED_HALLUCINATION" not in ctx.session_history
        assert "grounded answer" in ctx.session_history
        assert "second q" in ctx.session_history

    def test_legacy_assistant_entries_still_recall(self, mm):
        # Entries written before the gate (no ``verified`` key) remain recallable
        import asyncio
        os.makedirs(os.path.join(mm.root, ".nexus", "logs", "sessions"), exist_ok=True)
        with open(self._session_file(mm), "w", encoding="utf-8") as f:
            json.dump([
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "legacy answer"},
            ], f)
        ctx = asyncio.run(mm.prefetch_all("q"))
        assert "legacy answer" in ctx.session_history


class TestMemoryToolProvenance:
    def _tool(self, tmp_path):
        from extensions.tools.built_in.memory.scripts.memory import MemoryTool
        return MemoryTool(root_dir=str(tmp_path)), str(tmp_path)

    def test_store_records_unverified_claim_provenance(self, tmp_path):
        import asyncio
        tool, root = self._tool(tmp_path)
        result = asyncio.run(tool.execute(
            "store", key="fact", content="the sky is green"
        ))
        assert result.success
        store_path = tmp_path / ".nexus" / "memory" / "store.json"
        store = json.loads(store_path.read_text(encoding="utf-8"))
        assert store["fact"]["source"] == "llm_claim"
        assert store["fact"]["verified"] is False

    def test_store_requires_citation_for_verified(self, tmp_path):
        import asyncio
        tool, root = self._tool(tmp_path)
        # A bare ``verified=True`` without a citation is still an llm claim
        result = asyncio.run(tool.execute(
            "store", key="k", content="x", verified=True
        ))
        assert result.success
        store = json.loads((tmp_path / ".nexus" / "memory" / "store.json").read_text(encoding="utf-8"))
        assert store["k"]["source"] == "llm_claim"
        assert store["k"]["verified"] is False

    def test_store_cited_verified_result_is_recorded(self, tmp_path):
        import asyncio
        tool, root = self._tool(tmp_path)
        result = asyncio.run(tool.execute(
            "store", key="k", content="verified fact",
            verified_result_id="run-42", source="verified_result",
        ))
        assert result.success
        store = json.loads((tmp_path / ".nexus" / "memory" / "store.json").read_text(encoding="utf-8"))
        assert store["k"]["source"] == "verified_result"
        assert store["k"]["verified"] is True
        assert store["k"]["verified_result_id"] == "run-42"
