import ast
from pathlib import Path


GUI_SOURCE = Path(__file__).resolve().parents[3] / "gui" / "api.py"


def _handler(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(GUI_SOURCE.read_text(encoding="utf-8"))
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _to_thread_calls(node: ast.AsyncFunctionDef):
    return [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
    ]


def test_upload_and_website_ingestion_offload_post_write_work():
    assert len(_to_thread_calls(_handler("upload_files"))) >= 3
    assert len(_to_thread_calls(_handler("import_website_source"))) >= 5
    assert len(_to_thread_calls(_handler("patch_source"))) >= 1
    assert len(_to_thread_calls(_handler("delete_source"))) >= 1


def test_source_library_writes_are_atomic_and_serialized():
    source = GUI_SOURCE.read_text(encoding="utf-8")
    assert "_SOURCE_LIBRARY_LOCK = threading.RLock()" in source
    assert "_interprocess_event_lock(_SOURCE_LIBRARY_PATH)" in source
    assert "os.replace(temporary, _SOURCE_LIBRARY_PATH)" in source
