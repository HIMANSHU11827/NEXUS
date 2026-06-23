"""Tests for NexusLoop evolution hooks."""
__version__ = "1.0.0"

from orchestrators.loop import NexusLoop, SCAState, PermissionPolicy, ToolCall, HookRegistry


class TestNexusLoopInstantiation:
    def test_instantiate(self, tmp_path):
        loop = NexusLoop(root_dir=str(tmp_path))
        assert loop is not None
        assert hasattr(loop, "_gaps_found")
        assert isinstance(loop._gaps_found, list)

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


class TestSCAState:
    def test_all_states_defined(self):
        assert SCAState.GROUNDING == "grounding"
        assert SCAState.PLANNING == "planning"
        assert SCAState.INFERENCE == "inference"
        assert SCAState.AUDITING == "auditing"
        assert SCAState.EXECUTION == "execution"
        assert SCAState.VERIFICATION == "verification"
        assert SCAState.EVOLVE == "evolve"
        assert len(SCAState) == 7


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


class TestHookRegistry:
    def test_register_and_trigger(self):
        registry = HookRegistry()
        results = []

        async def my_hook(*args, **kwargs):
            results.append("triggered")

        registry.register("on_state_change", my_hook)
        import asyncio
        asyncio.run(registry.trigger("on_state_change"))
        assert len(results) == 1
