import ast
from pathlib import Path


def _function(name: str):
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_generic_config_save_offloads_loader_persistence():
    node = _function("save_config")
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
        isinstance(arg, ast.Name) and arg.id == "_save_kernel_config_sync"
        for call in calls
        for arg in call.args
    )


def test_async_config_mutations_do_not_call_save_inline():
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "save"
            ):
                offenders.append((node.name, child.lineno))
    assert offenders == []


def test_plugin_filesystem_mutations_are_offloaded():
    for name, helper in (("create_local_plugin", "_create_local_plugin_sync"), ("delete_plugin", "_remove_plugin_tree_sync")):
        node = _function(name)
        calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
            and call.func.attr == "to_thread"
        ]
        assert any(
            any(isinstance(arg, ast.Name) and arg.id == helper for arg in call.args)
            for call in calls
        ), (name, helper)


def test_plugin_endpoints_do_not_write_or_remove_files_inline():
    offenders = []
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in {"create_local_plugin", "delete_plugin"}:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            attr = func.attr if isinstance(func, ast.Attribute) else ""
            name = func.id if isinstance(func, ast.Name) else ""
            if attr in {"open", "rmtree", "makedirs", "replace"} or name in {"open", "rmtree", "makedirs"}:
                offenders.append((node.name, child.lineno, attr or name))
    assert offenders == []


def test_session_metadata_writes_are_offloaded():
    tree = ast.parse(Path("gui/api.py").read_text(encoding="utf-8"))
    for name in {"rename_session", "chat"}:
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        assert any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
            and call.func.attr == "to_thread"
            and any(isinstance(arg, ast.Name) and arg.id == "_write_session_title_sync" for arg in call.args)
            for call in ast.walk(node)
        ), name
