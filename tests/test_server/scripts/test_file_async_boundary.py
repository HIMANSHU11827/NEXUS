import ast
from pathlib import Path


SERVER_SOURCE = Path(__file__).resolve().parents[3] / "apps" / "api" / "__init__.py"


def _async_handler(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing async handler: {name}")


def _uses_to_thread(node: ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
        for call in ast.walk(node)
    )


def test_workspace_file_handlers_offload_blocking_io():
    handlers = (
        "write_workspace_file",
        "create_workspace_file",
        "rename_workspace_file",
        "delete_workspace_file",
        "move_workspace_file",
        "zip_workspace_file",
        "unzip_workspace_file",
        "list_files",
    )
    assert all(_uses_to_thread(_async_handler(name)) for name in handlers)
