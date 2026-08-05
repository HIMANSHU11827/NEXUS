from orchestrators.v5.core import NexusLoopV5
from orchestrators.v5.perceive import PerceivedInput, InputType, Intent
import asyncio


def test_v5_planning_gate_skips_conversation_and_factual_questions(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    assert loop._requires_planning("hello") is False
    assert loop._requires_planning("how do you do") is False
    assert loop._requires_planning("what is artificial intelligence?") is False
    assert loop._requires_planning("explain recursion") is False


def test_v5_planning_gate_plans_only_actionable_work(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    assert loop._requires_planning("read README.md and summarize it") is True
    assert loop._requires_planning("fix the failing test and run pytest") is True
    assert loop._requires_planning("research the latest Python release") is True
    assert loop._requires_planning("tell me today's news") is True


def test_v5_model_planning_decision_overrides_heuristic(tmp_path, monkeypatch):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="please handle this unusual request",
        input_type=InputType.TEXT,
        intent=Intent.UNKNOWN,
        confidence=0.2,
    )

    async def direct(*_args, **_kwargs):
        return "DIRECT"

    monkeypatch.setattr(loop, "_safe_model_call", direct)
    asyncio.run(loop._decide_planning(perceived))
    assert perceived.metadata["planning_required"] is False
    assert perceived.metadata["planning_decision"] == "model:direct"


def test_v5_router_returns_full_runtime_policy(tmp_path, monkeypatch):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="fix the failing tests with parallel specialists",
        input_type=InputType.TEXT,
        intent=Intent.DEBUGGING,
        confidence=0.9,
    )

    async def route(*_args, **_kwargs):
        return '{"mode":"PLAN","tool":"command","hive":true,"mcp":false,"model":"strong","permission":"ask","sandbox":"normal","voice":false,"skills":true,"plugins":true,"compact":true,"evolution":true,"forge":false,"gap_finder":true,"background":true}'

    monkeypatch.setattr(loop, "_safe_model_call", route)
    asyncio.run(loop._decide_planning(perceived))
    loop._apply_execution_policy(perceived)
    assert perceived.metadata["hive_required"] is True
    assert perceived.metadata["tool_route"] == "command"
    assert perceived.metadata["permission_route"] == "ask"
    assert perceived.metadata["sandbox_route"] == "normal"
    assert loop.runtime.feature_hive is True


def test_planning_route_persists_through_registered_planning_tool(tmp_path, monkeypatch):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="build and test the small application",
        input_type=InputType.TEXT,
        intent=Intent.TASK,
        confidence=1.0,
    )
    captured = []

    async def plan_model(_perceived):
        return [
            {"description": "Inspect the project", "tool": "reading", "params": {}},
            {"description": "Implement the application", "tool": "creating", "params": {}},
            {"description": "Run the application tests", "tool": "test_runner", "params": {}},
        ]

    async def run_tool(call):
        captured.append(call)
        return "plan persisted"

    monkeypatch.setattr(loop, "_llm_plan_with_enforcement", plan_model)
    loop._run_tool = run_tool

    steps = asyncio.run(loop._plan_with_tool(perceived))

    assert len(steps) == 3
    assert len(captured) == 1
    assert captured[0].name == "planning"
    assert captured[0].params["action"] == "create"
    assert captured[0].params["plan_spec"]["steps"] == [
        "Inspect the project", "Implement the application", "Run the application tests"
    ]


def test_direct_fallback_does_not_claim_steps_completed(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="hello nexus",
        input_type=InputType.TEXT,
        intent=Intent.CHAT,
        confidence=1.0,
    )

    response = loop._compose_fallback_response(
        perceived,
        {"success": True, "plan": None, "actions": []},
    )

    assert "All steps completed successfully." not in response
    assert response == "Processed your request: hello nexus"


def test_plan_only_fallback_does_not_claim_tool_execution(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="read the file",
        input_type=InputType.TEXT,
        intent=Intent.UNKNOWN,
        confidence=1.0,
    )

    response = loop._compose_fallback_response(
        perceived,
        {"success": True, "plan": {"steps": [{"description": "read the file"}]}, "actions": []},
        plan_text="- read the file",
    )

    assert "A plan was created, but no tool was executed." in response
    assert "All steps completed successfully." not in response


def test_provider_failure_fallback_explains_configuration_problem(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    loop._last_model_error = "[PROVIDER_ERROR] status 401 authentication fails"
    perceived = PerceivedInput(
        original_input="tell me today's news",
        input_type=InputType.TEXT,
        intent=Intent.UNKNOWN,
        confidence=0.5,
    )

    response = loop._compose_fallback_response(
        perceived,
        {"success": True, "plan": None, "actions": []},
    )

    assert "provider rejected its API key" in response
    assert "Processed your request" not in response


def test_tool_failure_is_evidence_not_no_tools_claim(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="search today's news",
        input_type=InputType.TEXT,
        intent=Intent.RESEARCH,
        confidence=1.0,
    )
    text = loop._describe_tool_results({
        "success": False,
        "actions": [{"tool": "web_search", "status": "failed", "error": "network unavailable"}],
    })
    assert "web_search" in text
    assert "FAILED" in text
    assert "no tools" not in text.lower()


def test_reasoning_only_action_is_not_tool_evidence(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="plan this",
        input_type=InputType.TEXT,
        intent=Intent.TASK,
        confidence=1.0,
    )
    response = loop._compose_fallback_response(
        perceived,
        {"success": True, "plan": {"steps": [{"description": "understand"}]},
         "actions": [{"description": "understand", "success": True, "output": "Completed"}]},
        plan_text="- understand",
    )
    assert "no tool was executed" in response.lower()
    assert "All steps completed successfully." not in response


def test_response_replaces_model_no_tools_claim_when_action_failed(tmp_path, monkeypatch):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    perceived = PerceivedInput(
        original_input="search today's news",
        input_type=InputType.TEXT,
        intent=Intent.RESEARCH,
        confidence=1.0,
    )

    async def stream(*_args, **_kwargs):
        yield "No tools were executed; I could not fetch the news."

    monkeypatch.setattr(loop, "_stream_model", stream)
    items = asyncio.run(_collect_output(loop, perceived, {
        "success": False,
        "actions": [{"tool": "web_search", "status": "failed", "error": "network unavailable"}],
    }))
    response = items[-1]["output"]["response"]
    assert "no tools were executed" not in response.lower()
    assert "web_search" in response
    assert "network unavailable" in response


async def _collect_output(loop, perceived, result):
    return [item async for item in loop._generate_output(perceived, result)]
