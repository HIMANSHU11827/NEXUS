"""Integration tests: plan-retry backoff and run-context intermediate statuses."""

import asyncio
import time

import pytest

from nexus.run_context import RunContext, start_run_context


class TestPlanRetryBackoff:
    def test_enforcement_retries_with_backoff(self, tmp_path, monkeypatch):
        import logging

        import nexus.main_agent.retry as retry_module

        sleeps = []

        async def fake_sleep(delay, result=None):
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setenv("NEXUS_PLAN_RETRY_BACKOFF_BASE", "0.5")

        class FakePerceived:
            original_input = "create a file in the project"
            intent = type("Intent", (), {"value": "tool"})()

        class Host:
            def __init__(self):
                self.calls = 0
                self.logger = logging.getLogger("test")

            async def _llm_plan(self, perceived):
                self.calls += 1
                return []

            def _requires_real_tooling(self, perceived):
                return True

            def _planning_system_prompt(self):
                return "plan"

            async def _safe_model_call(self, messages, **kwargs):
                return "{}"

            def _get_tool_schemas(self, top_k=100):
                return []

            def _parse_plan_json(self, raw):
                return []

            def _plan_from_text(self, raw, task):
                return []

            def _tool_enforcement_message(self, task):
                return "[TOOL_ENFORCEMENT] plan must contain tool steps"

        host = Host()
        loop = asyncio.new_event_loop()
        try:
            bound = retry_module.V5RetryPolicy._llm_plan_with_enforcement
            steps = loop.run_until_complete(bound(host, FakePerceived(), max_retries=2))
        finally:
            loop.close()
        assert steps == []
        assert host.calls == 1
        assert len(sleeps) == 1
        assert sleeps[0] > 0

    def test_no_backoff_when_disabled(self, monkeypatch):
        import logging

        import nexus.main_agent.retry as retry_module

        sleeps = []

        async def fake_sleep(delay, result=None):
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setenv("NEXUS_PLAN_RETRY_BACKOFF_BASE", "0")
        monkeypatch.setenv("NEXUS_PLAN_RETRY_BACKOFF_MAX", "0")

        class FakePerceived:
            original_input = "run the tests"
            intent = type("Intent", (), {"value": "test"})()

        class Host:
            def __init__(self):
                self.logger = logging.getLogger("test")

            async def _llm_plan(self, perceived):
                return []

            def _requires_real_tooling(self, perceived):
                return True

            def _planning_system_prompt(self):
                return "plan"

            async def _safe_model_call(self, messages, **kwargs):
                return "{}"

            def _get_tool_schemas(self, top_k=100):
                return []

            def _parse_plan_json(self, raw):
                return []

            def _plan_from_text(self, raw, task):
                return []

            def _tool_enforcement_message(self, task):
                return "[TOOL_ENFORCEMENT] plan must contain tool steps"

        loop = asyncio.new_event_loop()
        try:
            bound = retry_module.V5RetryPolicy._llm_plan_with_enforcement
            steps = loop.run_until_complete(bound(Host(), FakePerceived(), max_retries=2))
        finally:
            loop.close()
        assert steps == []
        assert sleeps == []


class TestRunContextIntermediateStatus:
    def test_set_intermediate_status_and_finish(self, tmp_path):
        context = start_run_context(
            root=str(tmp_path),
            session_id="sess1",
            run_id="run1",
            prompt="do it",
        )
        assert context.set_intermediate_status("recovering", "tool failed; retrying")
        assert context.set_intermediate_status("blocked", "needs credentials")
        assert context.status == "blocked"
        assert context.finish("failed", "run.failed", "no creds")
        assert context.status == "failed"

    def test_invalid_status_rejected(self, tmp_path):
        context = start_run_context(
            root=str(tmp_path),
            session_id="sess1",
            run_id="run2",
            prompt="do it",
        )
        assert context.set_intermediate_status("quantum") is False
        assert context.status == "running"
        assert context.finish("completed", "run.completed")

    def test_terminal_cannot_reenter_intermediate(self, tmp_path):
        context = start_run_context(
            root=str(tmp_path),
            session_id="sess1",
            run_id="run3",
            prompt="do it",
        )
        context.finish("completed", "run.completed")
        assert context.set_intermediate_status("recovering") is False
        assert context.status == "completed"

    def test_persisted_status_survives_reload(self, tmp_path):
        context = start_run_context(
            root=str(tmp_path),
            session_id="sess1",
            run_id="run4",
            prompt="do it",
        )
        context.set_intermediate_status("waiting_for_permission", "needs approval")
        reloaded = RunContext(
            run_id="run4",
            session_id="sess1",
            root=str(tmp_path),
        )
        from nexus.run_context import _read_run_context_payload

        payload = _read_run_context_payload(reloaded.path)
        assert payload["status"] == "waiting_for_permission"
        assert reloaded.finish("completed", "run.completed")