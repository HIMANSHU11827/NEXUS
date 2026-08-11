import asyncio

import pytest
from fastapi import HTTPException


def test_workspace_mutation_path_rejects_escape():
    from server import _safe_workspace_mutation_path

    with pytest.raises(HTTPException) as error:
        _safe_workspace_mutation_path("../outside.txt")
    assert error.value.status_code == 403


def test_resume_dispatches_unfinished_checkpoint_through_live_loop(monkeypatch, tmp_path):
    import nexus.commands as commands

    class Checkpoint:
        root_dir = ""

        def _checkpoint_list(self, limit=0):
            return [{"file": str(tmp_path / "unfinished.json"), "phase": "planning"}]

        def _checkpoint_read(self, path):
            return {"phase": "planning", "context_summary": "finish the saved task"}

    class Loop:
        async def stream_run(self, prompt, **kwargs):
            assert "NEXUS_RESUME_CONTEXT" in prompt
            yield {"type": "done", "data": {"success": True, "response": "continued"}}

    monkeypatch.setattr(commands, "V5Checkpoint", Checkpoint, raising=False)
    # The handler imports V5Checkpoint locally, so patch the module it imports.
    import orchestrators.v5.checkpoint as checkpoint_module
    monkeypatch.setattr(checkpoint_module, "V5Checkpoint", Checkpoint)

    ctx = commands.CommandContext(loop=Loop(), extra={"root": str(tmp_path)})
    result = asyncio.run(commands._cmd_resume(ctx))
    assert result.success
    assert result.data["resumed"] is True
    assert result.output == "continued"
