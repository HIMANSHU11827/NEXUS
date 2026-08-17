import asyncio

from tools.shortcuts.scripts.shortcuts import ShortcutsTool


def test_shortcuts_list_on_file_returns_repair_hint(tmp_path):
    target = tmp_path / "workspace" / "todo.md"
    target.parent.mkdir()
    target.write_text("TODO LIST\n", encoding="utf-8")

    result = asyncio.run(ShortcutsTool(str(tmp_path)).execute(
        action="list", path="workspace/todo.md"
    ))

    assert result.success is False
    assert "Use action=info" in result.error
    assert "reading tool" in result.error
