import ast
from pathlib import Path


def _function(name: str):
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_artifact_endpoint_offloads_file_and_event_persistence():
    node = _function("create_artifact")
    calls = [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
    ]
    assert calls
    assert any(
        isinstance(arg, ast.Name) and arg.id == "_create_artifact_sync"
        for call in calls
        for arg in call.args
    )


def test_artifact_sync_helper_owns_event_emission():
    node = _function("_create_artifact_sync")
    names = {
        item.func.id
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
    }
    assert "append_work_event" in names
