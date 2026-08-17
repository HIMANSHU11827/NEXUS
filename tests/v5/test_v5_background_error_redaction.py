import asyncio

from nexus.main_agent.background_runner import V5BackgroundRunner


class _Runner(V5BackgroundRunner):
    def __init__(self):
        self.events = []

    async def _emit_runtime_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_background_failure_events_redact_secrets_and_are_bounded():
    async def scenario():
        runner = _Runner()

        async def broken():
            raise RuntimeError("provider token=sk-test-background-secret")

        runner._run_background(broken(), name="secret-job")
        await runner._drain_runner_tasks()
        failed = [event for event in runner.events if event[0][0] == "background.failed"]
        assert failed
        error = failed[-1][1]["payload"]["error"]
        assert "sk-test-background-secret" not in error
        assert "REDACTED" in error
        assert len(error) <= 300

    asyncio.run(scenario())
