"""Regression checks for blocking persistence in server async routes."""

import ast
from pathlib import Path


def _function(name: str):
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_session_rename_offloads_atomic_metadata_write():
    node = _function("rename_session")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
        and any(isinstance(arg, ast.Name) and arg.id == "_write_session_title_sync" for arg in call.args)
        for call in ast.walk(node)
    )


def test_session_rename_has_no_inline_file_write():
    node = _function("rename_session")
    offenders = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        attr = func.attr if isinstance(func, ast.Attribute) else ""
        name = func.id if isinstance(func, ast.Name) else ""
        if attr in {"open", "replace", "write_text", "makedirs"} or name in {"open", "replace", "makedirs"}:
            offenders.append((child.lineno, attr or name))
    assert offenders == []


def test_async_runtime_preference_routes_offload_persistence():
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "_save_runtime_preferences"
            ):
                offenders.append((node.name, child.lineno))
    assert offenders == []


def test_manage_route_offloads_all_configuration_io():
    node = _function("manage_runtime")
    forbidden = {
        "_load_nexus_config",
        "_save_nexus_config",
        "_load_claude_settings",
        "_save_claude_settings",
        "_sync_mcp_servers_file",
        "_save_tasks",
    }
    offenders = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        name = func.id if isinstance(func, ast.Name) else ""
        if name in forbidden:
            offenders.append((name, child.lineno))
    assert offenders == []


def test_workspace_and_mcp_config_routes_offload_configuration_io():
    names = {
        "create_mcp",
        "workspace_protected_add",
        "workspace_protected_remove",
        "workspace_instructions_save",
        "workspace_import",
    }
    forbidden = {
        "_load_nexus_config",
        "_save_nexus_config",
        "_sync_mcp_servers_file",
    }
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in names:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in forbidden:
                offenders.append((node.name, child.func.id, child.lineno))
    assert offenders == []


def test_protected_path_routes_use_reload_mutate_save_transaction():
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    for name in {"workspace_protected_add", "workspace_protected_remove"}:
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        assert any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
            and call.func.attr == "to_thread"
            and any(isinstance(arg, ast.Name) and arg.id == "_mutate_nexus_config_sync" for arg in call.args)
            for call in ast.walk(node)
        ), name

    transaction = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_mutate_nexus_config_sync"
    )
    calls = {
        call.func.id
        for call in ast.walk(transaction)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert {"_load_nexus_config", "_save_nexus_config", "_interprocess_event_lock"}.issubset(calls)


def test_task_mutations_offload_durable_persistence():
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    for name in {"create_task", "update_task"}:
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        assert any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
            and call.func.attr == "to_thread"
            and any(isinstance(arg, ast.Name) and arg.id == "_save_tasks" for arg in call.args)
            for call in ast.walk(node)
        ), name

    save = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_save_tasks")
    calls = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(save)
        if isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute))
    }
    assert {"_interprocess_event_lock", "mkstemp", "fsync"}.issubset(calls)


def test_training_launch_offloads_lock_and_process_start():
    node = _function("train_local_engine")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
        and any(isinstance(arg, ast.Name) and arg.id == "_start_training_sync" for arg in call.args)
        for call in ast.walk(node)
    )
    assert not any(
        isinstance(child, ast.With)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_interprocess_event_lock"
            for call in ast.walk(child)
        )
        for child in ast.walk(node)
    )


def test_server_chat_disconnect_requests_run_abort_before_producer_cleanup():
    node = _function("chat")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "request_abort"
        and any(isinstance(arg, ast.Constant) and arg.value == "client_disconnect" for arg in call.args)
        for call in ast.walk(node)
    )


def test_runtime_preferences_use_shared_config_transaction():
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_save_runtime_preferences")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_mutate_nexus_config_sync"
        for call in ast.walk(node)
    )
    forbidden = {"_load_nexus_config", "_save_nexus_config"}
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in forbidden
        for call in ast.walk(node)
    )


def test_plugin_settings_use_reload_mutate_save_transaction():
    tree = ast.parse(Path("apps/api/__init__.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "manage_runtime")
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "asyncio"
        and call.func.attr == "to_thread"
        and any(isinstance(arg, ast.Name) and arg.id == "_mutate_claude_settings_sync" for arg in call.args)
        for call in ast.walk(node)
    )
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_mutate_claude_settings_sync")
    calls = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(helper)
        if isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute))
    }
    assert {"_load_claude_settings", "_save_claude_settings", "_interprocess_event_lock"}.issubset(calls)
