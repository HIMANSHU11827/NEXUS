import pytest

from knowledge.indexer import NexusSemanticIndexer
from knowledge.rag.engine import NexusAtlasRAG


@pytest.fixture(autouse=True)
def _reset_rag_singleton():
    NexusAtlasRAG._reset_instance()
    yield
    NexusAtlasRAG._reset_instance()


def test_semantic_indexer_facade_uses_durable_rag(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("Nexus checkpoint recovery preserves unfinished tasks.", encoding="utf-8")
    indexer = NexusSemanticIndexer(str(tmp_path))

    message = indexer.index_workspace()
    results = indexer.search("checkpoint recovery")

    assert "Refreshed" in message
    assert results
    assert results[0]["file"] == "notes.md"
    assert indexer.status()["backend"] == "NexusAtlasRAG"


def test_semantic_indexer_can_update_one_file(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("initial", encoding="utf-8")
    indexer = NexusSemanticIndexer(str(tmp_path))

    assert "Surgical update complete" in indexer.index_workspace("notes.md")
    source.write_text("provider fallback recovery", encoding="utf-8")
    assert "Surgical update complete" in indexer.index_workspace("notes.md")
    assert "provider" in indexer.retrieve_as_text("provider")


def test_rag_instances_are_isolated_by_vault(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "left.md").write_text("left workspace signal", encoding="utf-8")
    (right / "right.md").write_text("right workspace signal", encoding="utf-8")

    first = NexusSemanticIndexer(str(left))
    second = NexusSemanticIndexer(str(right))
    first.index_workspace()
    second.index_workspace()

    assert first.status()["index_path"] != second.status()["index_path"]
    assert first.search("left signal")[0]["file"] == "left.md"
    assert second.search("right signal")[0]["file"] == "right.md"
