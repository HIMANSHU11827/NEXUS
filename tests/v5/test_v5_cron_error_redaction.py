from nexus.main_agent.cron import V5Cron


class _Lifecycle:
    def __init__(self):
        self.errors = []

    def fail_task(self, task_id, error):
        self.errors.append((task_id, error))


def test_cron_failure_records_redacted_bounded_error():
    lifecycle = _Lifecycle()
    V5Cron()._cron_record_result(
        lifecycle,
        "cron-1",
        None,
        "provider token=sk-test-cron-secret",
    )

    assert lifecycle.errors
    error = lifecycle.errors[0][1]
    assert "sk-test-cron-secret" not in error
    assert "REDACTED" in error
    assert len(error) <= 4000
