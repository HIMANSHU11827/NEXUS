"""V5 plan-path regression tests.

The canonical plan file is ``workspace/todo.md`` (lowercase, written by the
``planning`` tool). ``_read_todo_md`` must read the canonical path first and
fall back to the legacy ``TODO.md`` so a case-sensitive filesystem never
loses the plan (audit P39).
"""

import os

from nexus.main_agent.core import NexusLoopV5


def _bare_loop_with_root(root: str) -> NexusLoopV5:
    """Construct a NexusLoopV5 without running its heavy initializer."""
    loop = object.__new__(NexusLoopV5)
    loop.root_dir = root
    return loop


def _filesystem_is_case_sensitive(path) -> bool:
    """True when the filesystem distinguishes ``todo.md`` from ``TODO.md``."""
    probe = path / "case_probe"
    probe.write_text("lower", encoding="utf-8")
    upper = path / "CASE_PROBE"
    upper.write_text("upper", encoding="utf-8")
    result = probe.read_text(encoding="utf-8") == "lower"
    probe.unlink(missing_ok=True)
    upper.unlink(missing_ok=True)
    return result


def test_reads_canonical_lowercase_todo_md(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "todo.md").write_text("canonical plan", encoding="utf-8")

    loop = _bare_loop_with_root(str(tmp_path))

    assert loop._read_todo_md() == "canonical plan"


def test_prefers_canonical_over_legacy_when_case_matters(tmp_path):
    if not _filesystem_is_case_sensitive(tmp_path):
        return  # both names collide on case-insensitive filesystems
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "todo.md").write_text("canonical plan", encoding="utf-8")
    (workspace / "TODO.md").write_text("legacy plan", encoding="utf-8")

    loop = _bare_loop_with_root(str(tmp_path))

    assert loop._read_todo_md() == "canonical plan"


def test_falls_back_to_legacy_uppercase_todo_md(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "TODO.md").write_text("legacy plan", encoding="utf-8")

    loop = _bare_loop_with_root(str(tmp_path))

    assert loop._read_todo_md() == "legacy plan"


def test_returns_empty_when_no_plan_exists(tmp_path):
    loop = _bare_loop_with_root(str(tmp_path))

    assert loop._read_todo_md() == ""


def test_ignores_unreadable_plan_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = workspace / "todo.md"
    plan.write_text("x", encoding="utf-8")
    loop = _bare_loop_with_root(str(tmp_path))

    try:
        os.chmod(plan, 0o000)
    except OSError:
        return  # filesystem does not enforce permissions
    try:
        with open(plan, "r", encoding="utf-8"):
            return  # permissions not enforced on this platform (Windows)
    except OSError:
        pass
    try:
        assert loop._read_todo_md() == ""
    finally:
        os.chmod(plan, 0o644)
