import ast
from pathlib import Path


def _function(name: str):
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_provider_ping_offloads_blocking_network_probe():
    node = _function("ping_provider")
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
        isinstance(arg, ast.Name) and arg.id == "_ping_provider_sync"
        for call in calls
        for arg in call.args
    )


def test_provider_ping_sync_helper_owns_urlopen():
    node = _function("_ping_provider_sync")
    attrs = {
        item.func.attr
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
    }
    assert "urlopen" in attrs
