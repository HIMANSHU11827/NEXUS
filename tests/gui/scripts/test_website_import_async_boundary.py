import ast
from pathlib import Path


GUI_SOURCE = Path(__file__).resolve().parents[3] / "gui" / "api.py"


def test_website_import_offloads_validation_fetch_and_persistence():
    tree = ast.parse(GUI_SOURCE.read_text(encoding="utf-8"))
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "import_website_source"
    )
    calls = [
        call for call in ast.walk(handler)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
    ]
    assert len(calls) >= 3
