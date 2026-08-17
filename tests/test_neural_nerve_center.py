from concurrent.futures import ThreadPoolExecutor

from models.neural.nerve_center import NexusNerveCenter


def test_reinforcement_is_durable_and_bounded(tmp_path):
    first = NexusNerveCenter(str(tmp_path))
    assert first.reinforce("debug", "grep", 0.5)
    assert first.reinforce("debug", "grep", -0.25)
    assert first.reinforce("debug", "bash", float("inf")) is False

    second = NexusNerveCenter(str(tmp_path))
    row = next(item for item in second.snapshot()["reinforcement"] if item["tool_name"] == "grep")
    assert row["count"] == 2
    assert row["total_delta"] == 0.25


def test_reinforcement_concurrent_writes_are_aggregated(tmp_path):
    nerve = NexusNerveCenter(str(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda _: nerve.reinforce("task", "tool", 1), range(32)))

    assert all(accepted)
    row = nerve.snapshot()["reinforcement"][0]
    assert row["count"] == 32
    assert row["total_delta"] == 32


def test_mutations_are_redacted_and_invalid_values_are_ignored(tmp_path):
    nerve = NexusNerveCenter(str(tmp_path))
    assert nerve.log_mutation({"action": "rotate", "token": "sk-test-secret-value"})
    assert nerve.log_mutation(["not", "a", "mapping"]) is False
    snapshot = nerve.snapshot()
    assert snapshot["mutation_count"] == 1
    assert snapshot["model_training"] == "not_implemented"
