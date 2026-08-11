from benchmarks.nexus_agent_benchmark import run


def test_provider_independent_framework_benchmark_passes():
    report = run()
    assert report["provider_independent"] is True
    assert report["passed"] == report["total"]
    assert report["pass_rate"] == 1.0
