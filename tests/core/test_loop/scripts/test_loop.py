"""Tests for NexusLoop evolution hooks."""
__version__ = "1.0.0"

import asyncio
from datetime import datetime

from nexus.run_context import load_run_context
from orchestrators.loop import HookRegistry, NexusLoop, PermissionPolicy, ToolCall
from tools.planning.scripts.planning import PlanningTool


class _ProviderErrorBrain:
    @staticmethod
    def _looks_like_provider_error(value):
        return str(value).lower().startswith("[provider_error]") or str(value).lower().startswith("error:")

    @staticmethod
    def stream_generate(**_kwargs):
        yield "[PROVIDER_ERROR]: connection refused"

    @staticmethod
    def generate(**_kwargs):
        return "Error: connection refused"


class TestNexusLoopInstantiation:
    def test_instantiate(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        assert loop is not None
        assert hasattr(loop, "_gaps_found")
        assert isinstance(loop._gaps_found, list)

    def test_provider_stream_error_is_not_rendered_as_assistant_content(self, tmp_path, monkeypatch):
        import asyncio

        loop = NexusLoop(root_dir=str(tmp_path))
        monkeypatch.setitem(loop.kernel._instances, "moe", _ProviderErrorBrain())

        async def collect():
            return [chunk async for chunk in loop._stream_model([{"role": "user", "content": "hello"}])]

        with __import__("pytest").raises(RuntimeError, match="Provider stream failed"):
            asyncio.run(collect())

    def test_hooks_registered(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        assert loop.hooks is not None
        assert isinstance(loop.hooks, HookRegistry)

    def test_evolution_methods_exist(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        assert hasattr(loop, "_handle_tool_failure")
        assert hasattr(loop, "_fill_gap_during_session")
        assert hasattr(loop, "_fill_gap")
        assert hasattr(loop, "_retry_gap")


class TestToolCall:
    def test_create(self):
        tc = ToolCall("test_tool", {"key": "value"}, "call_123")
        assert tc.name == "test_tool"
        assert tc.params == {"key": "value"}
        assert tc.call_id == "call_123"

    def test_to_dict(self):
        tc = ToolCall("test", {"a": 1})
        d = tc.to_dict()
        assert d["name"] == "test"
        assert d["params"] == {"a": 1}

    def test_stable_call_id_for_same_tool_and_params(self):
        first = ToolCall("reading", {"path": "README.md"})
        second = ToolCall("reading", {"path": "README.md"})

        assert first.call_id == second.call_id
        assert first.call_id.startswith("call_")

    def test_tool_name_call_id_and_params_are_normalized(self):
        tc = ToolCall("bad tool/name!", "raw", "id with spaces!")

        assert tc.name == "bad_tool_name_"
        assert tc.params == {"value": "raw"}
        assert tc.call_id == "id_with_spaces_"


class TestProviderToolProtocolRecovery:
    def test_extracts_colon_function_call_with_malformed_value_quote(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls(
            '<function: web_search>\n'
            '<param name="query" value="today latest news headlines</param>\n'
            '<param name="max_results" value="8</param>\n'
            '</function>'
        )

        assert len(calls) == 1
        assert calls[0].name == "web_search"
        assert calls[0].params == {"query": "today latest news headlines", "max_results": 8}

    def test_removes_colon_function_protocol_from_chat_text(self):
        raw = '<function: web_search>\n<param name="query" value="news</param>\n</function>'
        assert NexusLoop._strip_internal_tool_protocol(raw).strip() == ""
        assert NexusLoop._contains_tool_protocol(raw) is True

    def test_removes_plain_function_wrapper_from_chat_text(self):
        raw = '<function>\nweb_search(query="latest news", max_results: 5)\n</function>'
        assert NexusLoop._strip_internal_tool_protocol(raw).strip() == ""
        assert NexusLoop._contains_tool_protocol(raw) is True

    def test_failed_tool_observation_is_not_cacheable(self):
        assert NexusLoop._observation_is_failure("[web_search]: Error — timeout") is True
        assert NexusLoop._observation_is_failure("[web_search]: useful result") is False

    def test_web_query_keeps_requested_subject(self):
        query = NexusLoop._normalize_web_query(
            "latest news headlines",
            "Find one current NASA news headline and summarize it in one sentence.",
        )
        assert "nasa" in query.lower()
        assert "news news" not in query.lower()

    def test_stale_todo_plan_is_not_matched_to_a_new_task(self):
        stale_plan = "TODO LIST\nTASK NAME: Build a website\nPHASE 1: Core Implementation"
        assert NexusLoop._todo_matches_task(stale_plan, "Find current NASA news") is False


class TestPlanningTool:
    def test_missing_model_plan_fails_instead_of_writing_a_generic_template(self, tmp_path):
        tool = PlanningTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute(goal="Tell me today's news"))

        assert result.success is False
        assert "Planning failed" in result.error
        assert not (tmp_path / "todo.md").exists()

    def test_model_generated_plan_is_saved_without_replacing_it_with_template(self, tmp_path):
        tool = PlanningTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute(
            goal="Tell me today's news",
            plan_spec={
                "plan_type": "simple",
                "steps": [
                    "Search major Indian and international news sources published today",
                    "Cross-check the publication date and headline details for each selected story",
                    "Group the verified updates into a short India, world, business, and sports briefing",
                    "Include the sources used with the final news summary",
                ],
            },
        ))

        assert result.success is True
        assert result.metadata["source"] == "llm"
        assert "Search major Indian and international news sources published today" in result.output
        assert "Define the live-information target" not in result.output
        assert (tmp_path / "todo.md").read_text(encoding="utf-8").strip() == result.output

    def test_live_research_uses_numbered_simple_plan_and_saves(self, tmp_path):
        tool = PlanningTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute(
            goal="Find one current NASA news headline",
            plan_spec={"plan_type": "simple", "steps": [
                "Search NASA newsroom and other current space-news sources for a new headline",
                "Confirm the publication date and story details against the NASA source",
                "Write a one-sentence summary of the verified headline",
            ]},
        ))

        assert result.success is True
        assert "TASK NAME: Find one current NASA news headline" in result.output
        assert "PLAN TYPE: Simple" in result.output
        assert "1. [ ] Search NASA newsroom and other current space-news sources for a new headline" in result.output
        assert "PHASE 1:" not in result.output
        assert "Core Implementation" not in result.output
        assert (tmp_path / "todo.md").read_text(encoding="utf-8").strip() == result.output

    def test_complex_task_uses_phases_with_unnumbered_subgoals(self, tmp_path):
        tool = PlanningTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute(
            goal="Build a full web application with API backend and database",
            plan_spec={"plan_type": "phased", "phases": [
                {"title": "Define the application scope", "subgoals": ["List the user journeys", "Identify API and data requirements"]},
                {"title": "Build the application", "subgoals": ["Implement the frontend", "Implement the API and database"]},
            ]},
        ))

        assert result.success is True
        assert "PLAN TYPE: Phased" in result.output
        assert "PHASE 1: Define the application scope" in result.output
        assert "- [ ] List the user journeys" in result.output
        assert "1. [ ]" not in result.output

    def test_add_complete_and_update_todos(self, tmp_path):
        tool = PlanningTool(root_dir=str(tmp_path))
        asyncio.run(tool.execute(goal="Research current space news", plan_spec={"plan_type": "simple", "steps": [
            "Search current space-news sources", "Verify dates and sources", "Draft a concise report",
        ]}))
        added = asyncio.run(tool.execute(action="add", item="Compare two sources"))
        assert "4. [ ] Compare two sources" in added.output

        completed = asyncio.run(tool.execute(action="complete", item="Compare two sources"))
        assert "4. [x] Compare two sources" in completed.output

        updated = asyncio.run(tool.execute(action="update", old_text="Draft a concise report", new_text="Prepare the final report"))
        assert "Prepare the final report" in updated.output


class TestHookRegistry:
    def test_register_and_trigger(self):
        registry = HookRegistry()
        results = []

        async def my_hook(*args, **kwargs):
            results.append("triggered")

        registry.register("pre_llm_call", my_hook)
        import asyncio
        asyncio.run(registry.trigger("pre_llm_call"))
        assert len(results) == 1


class TestVoiceModeCleaning:
    def test_voice_mode_cleaning(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        
        # Mock stream_run to yield nothing
        async def mock_stream_run(*args, **kwargs):
            if False:
                yield {}
        monkeypatch.setattr(loop, "stream_run", mock_stream_run)
        
        # Run loop.run with a voice prompt
        prompt = "Yeah\n\n[VOICE_MODE]: Keep it extremely brief (max 15 words). Conversational. No markdown."
        import asyncio
        asyncio.run(loop.run(prompt, voice_mode=True))
        
        # Verify user message in memory is cleaned
        assert len(loop.memory) >= 1
        user_msg = next((m for m in loop.memory if m["role"] == "user"), None)
        assert user_msg is not None
        assert user_msg["content"] == "Yeah"


class TestSoulLoading:
    def test_ensure_soul_file_creates_when_missing(self, tmp_path):
        NexusLoop(root_dir=str(tmp_path))
        nexus_path = tmp_path / "docs" / "NEXUS.md"
        assert nexus_path.exists(), "docs/NEXUS.md should be auto-seeded"
        content = nexus_path.read_text(encoding="utf-8")
        assert "NEXUS Identity & Soul" in content
        assert "sovereign autonomous agent" in content

    def test_ensure_soul_file_does_not_overwrite(self, tmp_path):
        nexus_path = tmp_path / "docs" / "NEXUS.md"
        nexus_path.parent.mkdir(parents=True, exist_ok=True)
        nexus_path.write_text("# Custom Soul", encoding="utf-8")
        NexusLoop(root_dir=str(tmp_path))
        assert nexus_path.read_text(encoding="utf-8") == "# Custom Soul"

    def test_load_soul_md_returns_content(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        content = loop._load_soul_md()
        assert "NEXUS Identity & Soul" in content

    def test_load_soul_md_fallback_when_deleted(self, tmp_path, monkeypatch):
        from orchestrators.loop import DEFAULT_AGENT_IDENTITY
        loop = NexusLoop(root_dir=str(tmp_path))
        nexus_path = tmp_path / "docs" / "NEXUS.md"
        nexus_path.unlink()
        content = loop._load_soul_md()
        assert content == DEFAULT_AGENT_IDENTITY


class TestPromptFilesLoading:
    def test_load_prompt_files_finds_agents_md(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Agent Instructions\nDo X", encoding="utf-8")
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
        result = loop._load_prompt_files()
        assert "AGENTS.md" in result
        assert "Do X" in result

    def test_load_prompt_files_finds_claude_md(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Claude Instructions\nBe helpful", encoding="utf-8")
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
        result = loop._load_prompt_files()
        assert "CLAUDE.md" in result
        assert "Be helpful" in result

    def test_load_prompt_files_finds_dot_cursorrules(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        cr = tmp_path / ".cursorrules"
        cr.write_text("some rules", encoding="utf-8")
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
        result = loop._load_prompt_files()
        assert ".cursorrules" in result
        assert "some rules" in result

    def test_load_prompt_files_finds_mdc_rules(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "python.mdc").write_text("Python rules", encoding="utf-8")
        (rules_dir / "typescript.mdc").write_text("TS rules", encoding="utf-8")
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
        result = loop._load_prompt_files()
        assert "python.mdc" in result
        assert "typescript.mdc" in result
        assert "Python rules" in result
        assert "TS rules" in result

    def test_load_prompt_files_empty_when_no_files(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
        result = loop._load_prompt_files()
        assert result == ""


class TestAgentExecutionContract:
    def test_audit_rejects_unknown_tool_even_when_bypass_is_enabled(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            loop.operator_bypass_mode = True

            class FakeRegistry:
                def list_tools(self):
                    return {"bash": object()}

            monkeypatch.setattr(type(loop), "tool_registry", property(lambda _self: FakeRegistry()))

            approved = await loop._audit_and_approve([ToolCall("not_real", {"command": "echo nope"})])

            assert approved is False

        asyncio.run(exercise())

    def test_checklist_policy_allows_exact_preauthorized_command(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            loop.operator_bypass_mode = False
            loop.policy = PermissionPolicy.CHECKLIST
            loop.checklist = ["npm test"]
            loop.session_id = "session-policy"
            loop._current_turn_id = "turn-policy"
            loop.permissions._decision_log = []

            class FakeRegistry:
                def list_tools(self):
                    return {"terminal": object()}

            monkeypatch.setattr(type(loop), "tool_registry", property(lambda _self: FakeRegistry()))

            async def noop_hooks(*_args, **_kwargs):
                return None

            loop.kernel.plugins.trigger_hooks = noop_hooks

            approved = await loop._audit_and_approve([ToolCall("terminal", {"command": "npm test"})])

            assert approved is True
            decision = loop.permissions.get_decision_log(limit=1)[0]
            assert decision["run_id"] == "turn-policy"
            assert decision["turn_id"] == "turn-policy"
            assert decision["session_id"] == "session-policy"
            assert decision["surface"] == "loop"

        asyncio.run(exercise())

    def test_checklist_policy_denies_similar_non_exact_command(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            loop.operator_bypass_mode = False
            loop.policy = PermissionPolicy.CHECKLIST
            loop.checklist = ["npm test"]

            class FakeRegistry:
                def list_tools(self):
                    return {"terminal": object()}

            monkeypatch.setattr(type(loop), "tool_registry", property(lambda _self: FakeRegistry()))

            async def noop_hooks(*_args, **_kwargs):
                return None

            loop.kernel.plugins.trigger_hooks = noop_hooks

            approved = await loop._audit_and_approve([ToolCall("terminal", {"command": "npm test -- --watch"})])

            assert approved is False

        asyncio.run(exercise())

    def test_same_loop_rejects_concurrent_runs(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            started = asyncio.Event()
            release = asyncio.Event()

            async def controlled_run(*_args, **_kwargs):
                started.set()
                await release.wait()
                yield {"type": "content", "data": "done"}

            monkeypatch.setattr(loop, "_stream_run_impl", controlled_run)

            first = asyncio.create_task(loop.run("first"))
            await started.wait()
            with __import__("pytest").raises(RuntimeError, match="already active"):
                await loop.run("second")
            release.set()
            assert await first == "done"
            assert loop.is_running is False

        asyncio.run(exercise())

    def test_stream_run_persists_successful_run_context(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            loop.session_id = "session"

            async def fake_full_loop(*_args, **_kwargs):
                yield {"type": "content", "data": "ok"}

            monkeypatch.setattr(loop, "_full_loop", fake_full_loop)

            chunks = [chunk async for chunk in loop.stream_run(
                "hello",
                provider="openai",
                model="gpt-test",
                max_tokens=99,
                turn_id="run-context-ok",
            )]

            context = load_run_context(str(tmp_path), "session", "run-context-ok")
            assert chunks == [{"type": "content", "data": "ok"}]
            assert context["status"] == "success"
            assert context["terminal_event"] == "run.completed"
            assert context["provider"] == "openai"
            assert context["model"] == "gpt-test"
            assert context["max_tokens"] == 99
            assert context["prompt_preview"] == "hello"

        asyncio.run(exercise())

    def test_stream_run_persists_failed_run_context(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            loop.session_id = "session"

            async def fake_full_loop(*_args, **_kwargs):
                raise RuntimeError("provider exploded")
                yield {}

            monkeypatch.setattr(loop, "_full_loop", fake_full_loop)

            with __import__("pytest").raises(RuntimeError, match="provider exploded"):
                async for _chunk in loop.stream_run("hello", turn_id="run-context-fail"):
                    pass

            context = load_run_context(str(tmp_path), "session", "run-context-fail")
            assert context["status"] == "failed"
            assert context["terminal_event"] == "run.failed"
            assert context["error"] == "provider exploded"

        asyncio.run(exercise())

    def test_task_cancellation_closes_message_and_run_once(self, tmp_path, monkeypatch):
        async def exercise():
            loop = NexusLoop(root_dir=str(tmp_path))
            captured = []
            loop.work_event_sink = captured.append
            started = asyncio.Event()
            never = asyncio.Event()

            async def slow_full_loop(*_args, **_kwargs):
                started.set()
                await never.wait()
                if False:
                    yield {}

            monkeypatch.setattr(loop, "_full_loop", slow_full_loop)
            task = asyncio.create_task(loop.run("wait"))
            await started.wait()
            task.cancel()
            with __import__("pytest").raises(asyncio.CancelledError):
                await task

            terminals = [
                (event.get("event_type"), event.get("status"))
                for event in captured
            ]
            assert terminals.count(("message.failed", "cancelled")) == 1
            assert terminals.count(("run.cancelled", "cancelled")) == 1
            assert loop.is_running is False

        asyncio.run(exercise())

    def test_tool_chunks_are_explicitly_public_and_preserve_stream_sequence(self):
        async def exercise():
            loop = object.__new__(NexusLoop)
            loop.session_id = "session"
            loop._current_turn_id = "run"
            captured = []
            loop.work_event_sink = captured.append
            loop._work_kind_for_call = lambda *_args: "command"
            loop._work_action_for_call = lambda *_args: "Run command"
            loop._work_target_for_call = lambda *_args: "echo real"

            await loop._emit_tool_chunk(ToolCall("bash", {"command": "echo real"}, "call"), "real output", 4, "stdout")

            assert captured[0]["visibility"] == "public"
            assert captured[0]["stream"] == "stdout"
            assert captured[0]["sequence"] == 400000
            assert captured[0]["chunk"] == "real output"

        asyncio.run(exercise())

    def test_failed_command_propagates_exit_code_step_and_batch_failure(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        loop._current_turn_id = "failed-command"

        async def failed_stream(*_args, **_kwargs):
            yield "\n[EXIT_CODE]: 7"

        monkeypatch.setattr(loop.sandbox, "stream_execute", failed_stream)
        loop.sandbox.last_exit_code = 7
        call = ToolCall("bash", {"command": "cmd /c exit 7"}, "exit7")

        observations = asyncio.run(loop._execute_tools([call]))

        assert loop._last_run_failed is True
        assert any("Error —" in item and "code 7" in item for item in observations)
        assert any(event.get("event_type") == "plan.step.failed" for event in captured)
        command_failed = next(event for event in captured if event.get("status") == "error" and event.get("kind") == "command")
        assert command_failed["exit_code"] == 7
        assert len([
            event for event in captured
            if event.get("status") == "error" and event.get("kind") == "command"
        ]) == 1
        assert not any(event.get("event_type") == "plan.step.completed" for event in captured)

    def test_chat_only_tool_example_is_not_executed(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: False)

        async def ground(task):
            return [{"role": "user", "content": task}]

        async def model(_messages, **_kwargs):
            yield 'An example is reading({"path":"README.md"}).'

        async def must_not_audit(_calls):
            raise AssertionError("chat-only prose entered tool execution")

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", model)
        monkeypatch.setattr(loop, "_audit_and_approve", must_not_audit)
        monkeypatch.setattr(loop, "_write_session_bus", lambda *_args: None)
        monkeypatch.setattr(loop, "_start_background_finalization", lambda *_args: None)

        result = asyncio.run(loop.run("Explain the reading tool"))

        assert "example" in result
        assert not any(event.get("status") in {"queued", "running"} and event.get("tool") == "reading" for event in captured)

    def test_empty_model_response_closes_run_as_failed(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: False)

        async def ground(task):
            return [{"role": "user", "content": task}]

        async def empty_model(_messages, **_kwargs):
            if False:
                yield ""

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", empty_model)
        monkeypatch.setattr(loop, "_write_session_bus", lambda *_args: None)
        monkeypatch.setattr(loop, "_start_background_finalization", lambda *_args: None)

        result = asyncio.run(loop.run("hello"))

        assert "no response" in result
        assert any(event.get("event_type") == "run.failed" for event in captured)
        assert not any(event.get("event_type") == "run.completed" for event in captured)

    def test_permission_blocked_plan_closes_run_as_failed(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: True)

        async def ground(task):
            return [{"role": "user", "content": task}]

        async def model(_messages, **_kwargs):
            yield "tool-call"

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", model)
        monkeypatch.setattr(loop, "_extract_tool_calls", lambda _response: [ToolCall("reading", {"path": "README.md"}, "blocked")])
        monkeypatch.setattr(loop, "_audit_and_approve", lambda _calls: asyncio.sleep(0, result=False))
        monkeypatch.setattr(loop, "_write_session_bus", lambda *_args: None)
        monkeypatch.setattr(loop, "_start_background_finalization", lambda *_args: None)

        result = asyncio.run(loop.run("read README.md"))

        assert "blocked" in result.lower()
        assert any(event.get("event_type") == "run.failed" for event in captured)
        assert not any(event.get("event_type") == "run.completed" for event in captured)

    def test_successful_tool_step_has_balanced_lifecycle(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        loop._current_turn_id = "balanced"

        async def run_tool(_call):
            return "ok"

        monkeypatch.setattr(loop, "_run_tool", run_tool)
        result = asyncio.run(loop._run_tool_step(ToolCall("reading", {"path": "README.md"}, "read")))

        assert result == "ok"
        lifecycle = [event.get("event_type") for event in captured]
        assert lifecycle == ["plan.step.started", "plan.step.completed"]

    @__import__("pytest").mark.parametrize("provider_failure", ["exception", "text"])
    def test_verified_tool_work_uses_evidence_summary_when_final_provider_fails(self, tmp_path, monkeypatch, provider_failure):
        loop = NexusLoop(root_dir=str(tmp_path))
        loop.work_event_sink = lambda _event: None
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: True)

        async def ground(task):
            return [{"role": "user", "content": task}]

        calls = 0
        async def model(_messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield "tool-call"
                return
            if provider_failure == "exception":
                raise RuntimeError("OpenRouter API key is missing")
            yield "Error in stream: OpenRouter API key is missing"

        async def execute(_calls):
            return ["[bash]: REAL_OK"]

        async def verify(*_args):
            return {"success": True, "vaccine": ""}

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", model)
        monkeypatch.setattr(loop, "_extract_tool_calls", lambda response: [ToolCall("bash", {"command": "echo REAL_OK"}, "one")] if response == "tool-call" else [])
        monkeypatch.setattr(loop, "_audit_and_approve", lambda _calls: asyncio.sleep(0, result=True))
        monkeypatch.setattr(loop, "_execute_tools", execute)
        monkeypatch.setattr(loop, "_verify_all_parallel", verify)
        monkeypatch.setattr(loop, "_save_checkpoint", lambda *_args: None)
        monkeypatch.setattr(loop, "_log_mission_replay", lambda *_args: None)
        monkeypatch.setattr(loop, "_write_session_bus", lambda *_args: None)
        monkeypatch.setattr(loop, "_start_background_finalization", lambda *_args: None)

        output = asyncio.run(loop.run("run echo REAL_OK"))

        assert "Work completed and verified." in output
        assert "REAL_OK" in output
        assert "OpenRouter API key" not in output
        assert loop._last_run_failed is False

    def test_verified_multi_step_work_executes_new_tools_and_emits_public_progress(self, tmp_path, monkeypatch):
        """A verified tool result must not prevent the next real tool step."""
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: True)

        async def ground(task):
            return [{"role": "user", "content": task}]

        responses = iter([
            "<progress>I will search the current sources first.</progress>search-step",
            "<progress>The search found the file. I am opening it now.</progress>read-step",
            "<progress>This confirms the issue. I am editing the code.</progress>edit-step",
            "<progress>The change is ready. I am running tests.</progress>test-step",
            "Completed: changed the file and verified the tests passed.",
        ])

        async def model(_messages, **_kwargs):
            yield next(responses)

        calls = {
            "search-step": ToolCall("web_search", {"query": "current sources"}, "search"),
            "read-step": ToolCall("reading", {"path": "README.md"}, "read"),
            "edit-step": ToolCall("file_ops", {"action": "edit", "path": "README.md"}, "edit"),
            "test-step": ToolCall("bash", {"command": "python -m pytest"}, "test"),
        }
        executed = []

        async def execute(step_calls):
            executed.extend(call.name for call in step_calls)
            return [f"[{call.name}]: complete" for call in step_calls]

        async def verify(*_args):
            return {"success": True, "vaccine": ""}

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", model)
        monkeypatch.setattr(loop, "_extract_tool_calls", lambda response: [calls[response]] if response in calls else [])
        monkeypatch.setattr(loop, "_audit_and_approve", lambda _calls: asyncio.sleep(0, result=True))
        monkeypatch.setattr(loop, "_execute_tools", execute)
        monkeypatch.setattr(loop, "_verify_all_parallel", verify)
        monkeypatch.setattr(loop, "_save_checkpoint", lambda *_args: None)
        monkeypatch.setattr(loop, "_log_mission_replay", lambda *_args: None)
        monkeypatch.setattr(loop, "_write_session_bus", lambda *_args: None)
        monkeypatch.setattr(loop, "_start_background_finalization", lambda *_args: None)

        output = asyncio.run(loop.run("research, inspect, edit, and test"))

        assert executed == ["web_search", "reading", "file_ops", "bash"]
        assert output.startswith("Completed:")
        assert [event["payload"]["text"] for event in captured if event.get("event_type") == "assistant.progress"] == [
            "I will search the current sources first.",
            "The search found the file. I am opening it now.",
            "This confirms the issue. I am editing the code.",
            "The change is ready. I am running tests.",
        ]
        completed_run = next(event for event in captured if event.get("event_type") == "run.completed")
        assert isinstance(completed_run.get("duration_ms"), (int, float))
        assert completed_run["duration_ms"] >= 0

    def test_failed_command_closes_phase_message_and_run_as_failed(self, tmp_path, monkeypatch):
        loop = NexusLoop(root_dir=str(tmp_path))
        captured = []
        loop.work_event_sink = captured.append
        monkeypatch.setattr(loop, "_requires_real_tooling", lambda _task: True)

        async def ground(task):
            return [{"role": "user", "content": task}]

        model_calls = 0
        async def model(_messages):
            nonlocal model_calls
            model_calls += 1
            if model_calls == 1:
                yield "tool-call"
                return
            yield "Error in stream: OpenRouter API key is missing"

        async def failed_stream(*_args, **_kwargs):
            loop.sandbox.last_exit_code = 7
            yield "\n[EXIT_CODE]: 7"

        async def verify(*_args):
            return {"success": True, "vaccine": ""}

        monkeypatch.setattr(loop, "_ground_context", ground)
        monkeypatch.setattr(loop, "_stream_model", model)
        monkeypatch.setattr(loop.sandbox, "stream_execute", failed_stream)
        monkeypatch.setattr(loop, "_extract_tool_calls", lambda response: [ToolCall("bash", {"command": "cmd /c exit 7"}, "exit7")] if response == "tool-call" else [])
        monkeypatch.setattr(loop, "_audit_and_approve", lambda _calls: asyncio.sleep(0, result=True))
        monkeypatch.setattr(loop, "_verify_all_parallel", verify)
        monkeypatch.setattr(loop, "_save_checkpoint", lambda *_args: None)
        monkeypatch.setattr(loop, "_log_mission_replay", lambda *_args: None)

        output = asyncio.run(loop.run("run cmd /c exit 7"))

        terminal = [(event.get("event_type"), event.get("status")) for event in captured]
        assert "Work failed." in output
        assert "code 7" in output
        assert "OpenRouter API key" not in output
        assert ("plan.step.failed", "failed") in terminal
        assert ("phase.failed", "failed") in terminal
        assert ("message.failed", "failed") in terminal
        assert ("run.failed", "failed") in terminal
        assert ("plan.step.completed", "success") not in terminal
        assert ("phase.completed", "success") not in terminal
        assert ("run.completed", "success") not in terminal

    def test_stream_boundary_emits_failed_terminal_events_on_unexpected_error(self):
        async def exercise():
            loop = object.__new__(NexusLoop)
            loop.session_id = "session"
            loop._abort_flag = asyncio.Event()
            loop._current_turn_id = ""
            loop._last_run_failed = False
            captured = []
            loop.work_event_sink = captured.append

            async def broken_full_loop(*_args, **_kwargs):
                if False:
                    yield None
                raise RuntimeError("provider exploded")

            loop._full_loop = broken_full_loop
            try:
                async for _ in loop.stream_run("hello", turn_id="run-error"):
                    pass
            except RuntimeError as exc:
                assert str(exc) == "provider exploded"

            assert [event["event_type"] for event in captured] == ["message.failed", "run.failed"]
            assert all(event["status"] == "failed" for event in captured)

        asyncio.run(exercise())

    def test_runtime_emitter_produces_real_canonical_lifecycle_payload(self):
        async def exercise():
            loop = object.__new__(NexusLoop)
            loop.session_id = "session"
            loop._current_turn_id = "run-42"
            captured = []
            loop.work_event_sink = captured.append

            await loop._emit_runtime_event(
                "run.started", "Run started", "running",
                event_id="run_run-42", payload={"task": "inspect"},
            )

            assert captured == [{
                "id": "run_run-42", "event_type": "run.started", "run_id": "run-42",
                "turn_id": "run-42", "kind": "run", "title": "Run started",
                "action": "Run started", "status": "running", "parent_id": None,
                "payload": {"task": "inspect"}, "visibility": "public",
            }]

        asyncio.run(exercise())

    def test_aclose_drains_owned_background_finalizers(self):
        async def exercise():
            loop = object.__new__(NexusLoop)
            loop._background_tasks = set()
            completed = asyncio.Event()

            async def finalize(_task_desc, _messages):
                await asyncio.sleep(0)
                completed.set()

            loop._finalize_session = finalize
            loop._start_background_finalization("test", [])
            assert loop._background_tasks
            await loop.aclose()
            assert completed.is_set()
            assert not loop._background_tasks

        asyncio.run(exercise())

    def test_actionable_requests_require_real_tools(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        for prompt in (
            "code me a dino game",
            "make a report",
            "research current AI agents",
            "install the dependency",
            "delete the old file",
        ):
            assert loop._requires_real_tooling(prompt), prompt
        assert not loop._requires_real_tooling("what is artificial intelligence?")

    def test_inline_table_requests_do_not_enter_tool_mode(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        for prompt in (
            "make a table in chat and show me",
            "compare cats and dogs in a table",
            "make tbale in chat are and show us",
        ):
            assert not loop._requires_real_tooling(prompt), prompt

        assert loop._requires_real_tooling("compare the current project files in a table")

    def test_compact_reading_tag_is_parsed(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls('<reading path="package.json" />')
        assert len(calls) == 1
        assert calls[0].name == "reading"
        assert calls[0].params == {"path": "package.json"}

    def test_removed_file_ops_read_syntax_maps_to_reading(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls('<file_ops action="read" path="package.json" />')
        assert len(calls) == 1
        assert calls[0].name == "reading"
        assert calls[0].params == {"path": "package.json"}

    def test_explicit_file_read_recovers_missing_model_tool_call(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))

        calls = loop._extract_explicit_file_actions(
            "Inspect README.md and summarize config/provider.yml"
        )

        assert [call.name for call in calls] == ["reading", "reading"]
        assert [call.params["path"] for call in calls] == ["README.md", "config/provider.yml"]

    def test_live_web_request_recovers_missing_model_tool_call(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))

        calls = loop._extract_required_tool_call("search the web for today's latest news")

        assert len(calls) == 1
        assert calls[0].name == "web_search"
        assert calls[0].params["query"] == "today's latest news"

        typo_calls = loop._extract_required_tool_call("tell me current knews in ai")
        assert typo_calls[0].params["query"] == "latest AI news"
        normalized = loop._normalize_web_query(
            "artificial intelligence latest news 2025",
            "tell me current news in AI",
        )
        today = datetime.now().strftime("%B %d %Y").replace(" 0", " ")
        assert "2025" not in normalized
        assert "latest artificial intelligence news" in normalized
        assert today in normalized
        general = loop._normalize_web_query(
            "latest artificial intelligence news 2025",
            "tell me today's news",
        )
        assert "artificial intelligence" not in general
        assert "latest news headlines" in general
        assert today in general
        topical = loop._normalize_web_query(
            "latest news headlines 2025",
            "can you tell latest knews on semiconductor factories of India",
        )
        assert "semiconductor factories of India" in topical
        assert "2025" not in topical
        assert today in topical

    def test_final_response_must_preserve_web_evidence(self):
        observations = ["[web_search]: - [Story](https://example.com/story) — details"]

        assert not NexusLoop._final_response_contains_evidence("Here is what I found:", observations)
        assert not NexusLoop._final_response_contains_evidence("Here are today's headlines.", observations)
        assert NexusLoop._final_response_contains_evidence(
            "Story: https://example.com/story",
            observations,
        )

    def test_web_evidence_summary_is_readable_and_keeps_sources(self):
        summary = NexusLoop._deterministic_evidence_summary([
            "[web_search]: Web search results\n"
            "- [AI Story](https://example.com/ai) — Important AI update"
        ])

        assert summary.startswith("Summary of the verified web results:")
        assert "1. AI Story" in summary
        assert "https://example.com/ai" not in summary
        assert "[web_search]" not in summary

    def test_raw_search_tool_dump_is_not_accepted_as_final_answer(self):
        raw = "[web_search]: Web search results for: latest news\n- [Story](https://www.bing.com/news/apiclick?url=https://example.com)"
        assert NexusLoop._is_raw_tool_result_dump(raw) is True
        assert NexusLoop._is_raw_tool_result_dump("Today's news includes Story, based on the verified search results.") is False

    def test_compact_creating_body_is_parsed(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls('<creating path="game.html"><h1>Dino</h1></creating>')
        assert len(calls) == 1
        assert calls[0].name == "creating"
        assert calls[0].params["content"] == "<h1>Dino</h1>"

    def test_empty_tool_protocol_is_never_user_facing(self):
        response = "```tool_use\n[\n  \n]\n```"
        assert NexusLoop._strip_internal_tool_protocol(response) == ""

    def test_removed_file_ops_create_syntax_maps_to_creating_and_is_hidden(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        response = '```tool\nfile_ops.create({"path":"games/cat.html","content":"<html>cat</html>"})\n```'

        calls = loop._extract_tool_calls(response)

        assert len(calls) == 1
        assert calls[0].name == "creating"
        assert calls[0].params == {
            "path": "games/cat.html",
            "content": "<html>cat</html>",
        }
        assert loop._strip_internal_tool_protocol(response).strip() == ""

    def test_removed_file_ops_directory_create_syntax_becomes_mkdir(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls('```tool\nfile_ops.create({"path":"games"})\n```')

        assert len(calls) == 1
        assert calls[0].name == "bash"
        assert "New-Item -ItemType Directory" in calls[0].params["command"]
        assert "games" in calls[0].params["command"]

    def test_provider_write_alias_maps_to_creating(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls(
            '{"name":"write","arguments":{"path":"game.html","content":"ok"}}'
        )
        assert len(calls) == 1
        assert calls[0].name == "creating"
        assert calls[0].params == {"path": "game.html", "content": "ok"}

    def test_provider_string_arguments_are_decoded(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls(
            '{"name":"write","arguments":"{\\"path\\":\\"game.html\\",\\"content\\":\\"ok\\"}"}'
        )

        assert len(calls) == 1
        assert calls[0].name == "creating"
        assert calls[0].params == {"path": "game.html", "content": "ok"}

    def test_inline_tool_json_allows_braces_inside_string_values(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        calls = loop._extract_tool_calls(
            'creating({"path":"app.js","content":"function x() { return {ok: true}; }"})'
        )

        assert len(calls) == 1
        assert calls[0].name == "creating"
        assert calls[0].params["content"] == "function x() { return {ok: true}; }"
