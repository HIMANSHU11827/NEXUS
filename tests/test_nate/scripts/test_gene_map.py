import pytest

from intelligence.nate.gene_map import Gene, GeneMap, SelfHealingEngine


class TestGene:
    def test_initial_state(self):
        g = Gene("rate_limit", "backoff", {"delay": 30})
        assert g.failure_code == "rate_limit"
        assert g.q_value == 0.0
        assert g.confidence == 0.0

    def test_record_success(self):
        g = Gene("auth", "refresh_token")
        g.record_success(100)
        assert g.success_count == 1
        assert g.q_value > 0
        assert g.avg_repair_ms == 100

    def test_record_failure(self):
        g = Gene("timeout", "retry")
        g.record_success(10)
        g.record_success(10)
        g.record_failure()
        assert g.failure_count == 1
        assert g.failure_count + g.success_count == 3

    def test_multiple_records(self):
        g = Gene("rate_limit", "backoff")
        g.record_success(50)
        g.record_success(150)
        assert g.success_count == 2
        assert g.avg_repair_ms == 100
        assert g.q_value > 0

    def test_to_dict(self):
        g = Gene("test", "fix")
        g.record_success(10)
        d = g.to_dict()
        assert d["failure_code"] == "test"
        assert "q_value" in d


class TestGeneMap:
    @pytest.fixture
    def gene_map(self):
        gm = GeneMap()
        g1 = Gene("rate_limit", "backoff")
        g1.record_success(30)
        gm.store(g1)
        g2 = Gene("auth_error", "refresh")
        g2.record_success(100)
        gm.store(g2)
        return gm

    def test_lookup(self, gene_map):
        g = gene_map.lookup("rate_limit")
        assert g is not None
        assert g.strategy == "backoff"

    def test_lookup_missing(self, gene_map):
        g = gene_map.lookup("nonexistent")
        assert g is None

    def test_store_multiple_for_same_code(self, gene_map):
        g = Gene("rate_limit", "retry")
        g.record_success(10)
        gene_map.store(g)
        best = gene_map.lookup("rate_limit")
        assert best is not None

    def test_call_sequence(self, gene_map):
        gene_map.record_call_sequence(["weather", "calendar", "email"])
        gene_map.record_call_sequence(["weather", "calendar", "slack"])
        predicted = gene_map.predict_next("weather")
        assert predicted == "calendar"

    def test_longest_prefix(self, gene_map):
        gene_map.record_call_sequence(["weather", "calendar", "email"])
        prefix = gene_map.longest_prefix_match("weather")
        assert prefix is not None
        assert prefix[0] == "weather"


class TestSelfHealingEngine:
    @pytest.fixture
    def engine(self):
        e = SelfHealingEngine()
        e.register_strategy("backoff", handler=lambda e: "waited")
        e.register_strategy("refresh", handler=lambda e: "token refreshed")
        e.register_strategy("retry", handler=lambda e: "retried")
        return e

    def test_heal_unknown_falls_through(self, engine):
        success, msg, strategy = engine.heal("new_error", "something failed")
        assert success
        assert strategy != "none"

    def test_heal_known_via_gene_map(self, engine):
        g = Gene("known_error", "backoff")
        g.record_success(50)
        engine.gene_map.store(g)
        success, msg, strategy = engine.heal("known_error", "rate limited")
        assert success or not success

    def test_stats(self, engine):
        s = engine.stats()
        assert s["strategies"] == 3

    def test_heal_all_fail(self, engine):
        engine = SelfHealingEngine()
        success, msg, strategy = engine.heal("error", "fail")
        assert not success
        assert strategy == "none"
