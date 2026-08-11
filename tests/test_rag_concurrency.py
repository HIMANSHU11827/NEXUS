from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from rag.engine import NexusAtlasRAG, _rag_interprocess_lock


def test_shared_vault_mutex_serializes_transactions(tmp_path):
    index_path = str(tmp_path / "knowledge" / "_rag_index.json")
    barrier = threading.Barrier(2)
    state = {"active": 0, "max_active": 0}
    state_lock = threading.Lock()

    def transaction():
        barrier.wait()
        with _rag_interprocess_lock(index_path):
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.05)
            with state_lock:
                state["active"] -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: transaction(), range(2)))

    assert state["max_active"] == 1


def test_concurrent_surgical_indexing_preserves_all_documents(tmp_path):
    NexusAtlasRAG._reset_instance()
    vault = tmp_path / "knowledge"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = workspace / "first.txt"
    second = workspace / "second.txt"
    first.write_text("alpha document content", encoding="utf-8")
    second.write_text("beta document content", encoding="utf-8")

    rag = NexusAtlasRAG(str(vault))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda path: rag.index_workspace(file_path=str(path)),
                (first, second),
            )
        )

    assert all("complete" in result.lower() for result in results)
    assert "workspace/first.txt#c0" in rag._doc_store
    assert "workspace/second.txt#c0" in rag._doc_store
    persisted = json.loads((vault / "_rag_index.json").read_text(encoding="utf-8"))
    assert "workspace/first.txt#c0" in persisted
    assert "workspace/second.txt#c0" in persisted


def test_vector_cache_rehydrates_from_persisted_index(tmp_path):
    vault = tmp_path / "knowledge"
    NexusAtlasRAG._reset_instance()
    rag = NexusAtlasRAG(str(vault))
    rag.store_document("persisted.txt", "vector cache survives restart")
    assert rag.turbo_engine is not None
    assert "persisted.txt#c0" in rag.turbo_engine.store

    NexusAtlasRAG._reset_instance()
    restored = NexusAtlasRAG(str(vault))
    assert restored.turbo_engine is not None
    assert "persisted.txt#c0" in restored.turbo_engine.store


def test_rebuild_index_does_not_restore_stale_persisted_documents(tmp_path):
    vault = tmp_path / "knowledge"
    source = tmp_path / "live.txt"
    source.write_text("live rebuild content", encoding="utf-8")
    NexusAtlasRAG._reset_instance()
    rag = NexusAtlasRAG(str(vault))
    rag.store_document("missing.txt", "stale content")

    result = rag.rebuild_index()

    assert "missing.txt#c0" not in rag._doc_store
    assert "live.txt#c0" in rag._doc_store
    assert "Refreshed" in result


def test_concurrent_retrieval_during_indexing_has_stable_results(tmp_path):
    NexusAtlasRAG._reset_instance()
    vault = tmp_path / "knowledge"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.txt"
    source.write_text("stable retrieval evidence", encoding="utf-8")
    rag = NexusAtlasRAG(str(vault))

    def index():
        return rag.index_workspace(file_path=str(source))

    def retrieve():
        return rag.retrieve_as_text("stable evidence")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda fn: fn(), [index, retrieve, index, retrieve]))

    assert len(results) == 4
    assert "source.txt" in rag.retrieve_as_text("stable")
