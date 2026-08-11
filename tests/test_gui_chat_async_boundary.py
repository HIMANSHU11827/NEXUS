import ast
from pathlib import Path


def test_chat_offloads_session_metadata_read():
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.AsyncFunctionDef) and item.name == "chat")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
        and any(isinstance(arg, ast.Name) and arg.id == "_session_title_needs_write_sync" for arg in call.args)
        for call in ast.walk(node)
    )
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "open"
        for call in ast.walk(node)
    )
