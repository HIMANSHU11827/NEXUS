"""NATE routing-quality, OATS adaptation, and necessity-gate tests."""

from __future__ import annotations

import numpy as np
import pytest

from intelligence.nate.adaptive_schema import AdaptiveSchemaEngine, NATE_Route
from intelligence.nate.nate_engine import NATE


TOOLS = [
    ("web_search", "search the internet web for pages results query engine"),
    ("read_file", "read the contents of a file from disk filesystem path"),
    ("write_file", "write content into a file on disk filesystem path"),
    ("run_shell", "execute a shell terminal command process bash"),
    ("send_email", "send an email message to a recipient inbox smtp"),
]


def make_router() -> NATE_Route:
    r = NATE_Route()
    for name, desc in TOOLS:
        r.register_tool(name, desc)
    return r


# ── Routing quality ──────────────────────────────────────────────────────────

def test_registration_builds_embeddings_and_clusters():
    r = make_router()
    assert r._tool_embeddings is not None
    assert r._tool_embeddings.shape[0] == len(TOOLS)
    assert len(r._clusters) >= 1
    # every tool index is assigned to some cluster
    assert set(r._cluster_to_tool) == set(range(len(TOOLS)))
    # embeddings are unit-normalised
    norms = np.linalg.norm(r._tool_embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("search the internet web for query results", "web_search"),
        ("read the contents of a file from disk", "read_file"),
        ("execute a shell terminal command", "run_shell"),
        ("send an email message to a recipient", "send_email"),
    ],
)
def test_routing_picks_the_right_tool_first(query, expected):
    r = make_router()
    result = r.route(query)
    assert result["path"] in ("path1", "path2")
    assert result["tools"], f"no tools routed for {query!r}"
    assert result["tools"][0][0] == expected
    assert expected in r.get_tool_names_for_query(query)


def test_route_result_shape_and_dynamic_k_bounds():
    r = make_router()
    result = r.route("read the contents of a file from disk")
    for key in ("path", "tools", "confidence", "cluster_names", "latency_ms"):
        assert key in result
    assert 0 < len(result["tools"]) <= max(NATE_Route.DYNAMIC_K_MAX, len(TOOLS))
    # scores are sorted descending and confidence equals the best score
    scores = [t[1] for t in result["tools"]]
    assert scores == sorted(scores, reverse=True)
    assert result["confidence"] == pytest.approx(scores[0], abs=1e-6)
    # no duplicate tool names
    names = [t[0] for t in result["tools"]]
    assert len(names) == len(set(names))


def test_high_confidence_query_takes_path1():
    r = make_router()
    result = r.route("send an email message to a recipient inbox smtp")
    assert result["confidence"] >= NATE_Route.PATH1_THRESHOLD
    assert result["path"] == "path1"


def test_strap_clusters_near_duplicate_tools():
    r = NATE_Route()
    r.register_tool("file_reader", "read a file from disk")
    r.register_tool("file_reader_v2", "read a file from disk")
    # identical descriptions differ only by name token -> should be very similar
    sim = float(np.dot(r._tool_embeddings[0], r._tool_embeddings[1]))
    assert sim > 0.5
    if sim >= NATE_Route.STRAP_THRESHOLD:
        assert len(r._clusters) == 1
        res = r.route("read a file from disk")
        assert {t[0] for t in res["tools"]} == {"file_reader", "file_reader_v2"}


def test_metrics_track_queries_and_paths():
    r = make_router()
    r.route("read the contents of a file from disk")
    r.route("zzzz qqqq xxxx unrelated gibberish")
    s = r.stats()
    assert s["num_tools"] == len(TOOLS)
    assert s["total_queries"] == 2
    assert s["path1_pct"] + s["path2_pct"] + s["no_tool_pct"] == pytest.approx(100.0, abs=0.2)
    assert s["avg_latency_ms"] >= 0.0


# ── Necessity gate ───────────────────────────────────────────────────────────

def test_necessity_gate_blocks_unrelated_query():
    r = make_router()
    result = r.route("qwzx plkj vbnm zzzq unrelated gibberish tokens")
    assert result["confidence"] < NATE_Route.NECESSITY_THRESHOLD
    assert result["path"] == "no_tools"
    assert result["tools"] == []
    assert r.stats()["no_tool_pct"] == pytest.approx(100.0)


def test_empty_router_returns_no_tools():
    r = NATE_Route()
    result = r.route("anything at all")
    assert result["path"] == "no_tools"
    assert result["tools"] == []
    assert result["confidence"] == 0.0


def test_necessity_gate_propagates_through_engine():
    nate = NATE()
    for name, desc in TOOLS:
        nate.register_tool(name, desc)
    out = nate.get_schemas("qwzx plkj vbnm zzzq unrelated gibberish tokens")
    assert out["route_info"]["path"] == "no_tools"
    assert out["all"] == []
    assert out["routed"] == []


# ── OATS adaptation ──────────────────────────────────────────────────────────

def test_record_feedback_buckets_and_caps_history():
    r = make_router()
    for i in range(15):
        r.record_feedback("web_search", f"query number {i}", success=True)
    r.record_feedback("web_search", "bad query", success=False)
    assert len(r._feedback_success["web_search"]) == 10
    assert len(r._feedback_failure["web_search"]) == 1


def test_apply_oats_feedback_noop_without_feedback():
    r = make_router()
    before = r._tool_embeddings.copy()
    assert r.apply_oats_feedback() == 0
    assert np.allclose(before, r._tool_embeddings)
    assert r.stats()["oats_updates"] == 0


def test_apply_oats_feedback_moves_embedding_toward_success_query():
    r = make_router()
    query = "find flights to tokyo cheap airfare"
    idx = r._tool_names.index("web_search")
    q_emb = r._encode_text(query)
    before_sim = float(np.dot(r._tool_embeddings[idx], q_emb))

    for _ in range(5):
        r.record_feedback("web_search", query, success=True)
    updated = r.apply_oats_feedback(decay=0.5)

    assert updated == 1
    after_sim = float(np.dot(r._tool_embeddings[idx], q_emb))
    assert after_sim > before_sim
    assert np.linalg.norm(r._tool_embeddings[idx]) == pytest.approx(1.0, abs=1e-5)
    assert r.stats()["oats_updates"] == 1


def test_oats_failure_feedback_pushes_embedding_away():
    r = make_router()
    query = "delete the production database immediately"
    idx = r._tool_names.index("send_email")
    q_emb = r._encode_text(query)
    before_sim = float(np.dot(r._tool_embeddings[idx], q_emb))

    for _ in range(3):
        r.record_feedback("send_email", query, success=False)
    assert r.apply_oats_feedback(decay=0.5) == 1

    after_sim = float(np.dot(r._tool_embeddings[idx], q_emb))
    assert after_sim <= before_sim + 1e-9


def test_oats_adaptation_improves_routing_for_learned_query():
    r = make_router()
    query = "book a table at a restaurant tonight"
    for _ in range(5):
        r.record_feedback("web_search", query, success=True)
    r.apply_oats_feedback(decay=0.9)
    result = r.route(query)
    assert result["tools"], "expected tools after OATS adaptation"
    assert result["tools"][0][0] == "web_search"


def test_oats_rebuilds_clusters_and_keeps_index_consistent():
    r = make_router()
    r.record_feedback("read_file", "open a document", success=True)
    r.apply_oats_feedback(decay=0.3)
    assert r._tool_embeddings.shape[0] == len(TOOLS)
    assert set(r._cluster_to_tool) == set(range(len(TOOLS)))
    norms = np.linalg.norm(r._tool_embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


# ── Engine-level wiring ──────────────────────────────────────────────────────

def test_engine_oats_helpers_delegate_to_router():
    nate = NATE()
    for name, desc in TOOLS:
        nate.register_tool(name, desc)
    nate.record_router_feedback("web_search", "search the web for news", True)
    assert nate.apply_oats_feedback(decay=0.5) == 1
    stats = nate.router_stats()
    assert stats["num_tools"] == len(TOOLS)
    assert stats["oats_updates"] == 1


def test_engine_get_schemas_returns_relevant_tools():
    nate = NATE()
    for name, desc in TOOLS:
        nate.register_tool(name, desc)
    out = nate.get_schemas("read the contents of a file from disk")
    assert out["route_info"]["path"] in ("path1", "path2")
    assert out["all"], "expected converted schemas"
    assert "read_file" in [t[0] for t in out["routed"]]


def test_adaptive_schema_engine_always_loaded_tools_included():
    eng = AdaptiveSchemaEngine()
    for name, desc in TOOLS:
        eng.register_tool({"name": name, "description": desc, "parameters": {}})
    eng.set_always_loaded(["run_shell"])
    res = eng.get_schemas("read the contents of a file from disk")
    always_names = [t.get("n", t.get("name")) for t in res["always_loaded"]]
    assert always_names == ["run_shell"]
    assert "run_shell" not in [t.get("n", t.get("name")) for t in res["lazy_loaded"]]
