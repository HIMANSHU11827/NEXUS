import ast
from pathlib import Path


def _function(name: str):
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_todo_endpoint_offloads_persistence_transaction():
    node = _function("save_todo_endpoint")
    calls = [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
    ]

    assert calls, "todo persistence must not run inline on the async event loop"
    assert any(
        isinstance(arg, ast.Name) and arg.id == "_save_todo_sync"
        for call in calls
        for arg in call.args
    )


def test_todo_sync_helper_owns_event_log_mutation():
    node = _function("_save_todo_sync")
    names = {
        item.func.id
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
    }
    assert "write_workspace_todo_plan" in names
    assert "append_work_event" in names
