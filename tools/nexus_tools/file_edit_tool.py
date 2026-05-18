"""
NEXUS FILE EDIT TOOL — Claude Code FileEditTool + HyperAgents editor hybrid.
Supports: view, create, str_replace, insert, undo_edit
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional, List

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class FileHistory:
    """Undo history for file edits."""

    def __init__(self):
        self._history: Dict[str, List[str]] = {}

    def add(self, path: str, content: str):
        if path not in self._history:
            self._history[path] = []
        self._history[path].append(content)

    def undo(self, path: str) -> Optional[str]:
        if path in self._history and self._history[path]:
            return self._history[path].pop()
        return None


_file_history = FileHistory()


class FileEditTool(BaseTool):
    """Claude Code FileEditTool — advanced file operations with undo support."""

    name = "file_edit"
    description = "View, create, edit files with str_replace, insert, and undo support."
    aliases = ["editor", "file"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def _snapshot_if_file(self, path: str, reason: str) -> tuple[str, str]:
        if not os.path.isfile(path):
            return "", ""
        try:
            from core.os_power.rollback import RollbackManager
            snapshot = RollbackManager(self.root).snapshot_files([path], reason=reason)
            return f" [ROLLBACK_SNAPSHOT: {snapshot.id}]", snapshot.id
        except Exception:
            return " [ROLLBACK_SNAPSHOT_FAILED]", ""

    def _patch_baseline_if_file(self, path: str, reason: str) -> str:
        if not os.path.isfile(path):
            return ""
        try:
            from core.os_power.patch_ledger import PatchLedger
            return PatchLedger(self.root).baseline([path], label=reason)["id"]
        except Exception:
            return ""

    def _record_patch(self, baseline_id: str, path: str, reason: str, rollback_id: str = "") -> str:
        if not baseline_id:
            return " [PATCH_LEDGER_SKIPPED]"
        try:
            from core.os_power.patch_ledger import PatchLedger
            record = PatchLedger(self.root).record(baseline_id, [path], reason=reason, rollback_id=rollback_id)
            return f" [PATCH_LEDGER: {record.id}]"
        except Exception:
            return " [PATCH_LEDGER_FAILED]"

    def _resolve_path(self, path: str) -> str:
        candidate = os.path.abspath(path) if os.path.isabs(path) else os.path.abspath(os.path.join(self.root, path))
        root = os.path.abspath(self.root)
        try:
            if os.path.commonpath([root, candidate]) != root:
                raise ValueError(f"Path escapes project root: {path}")
        except ValueError as exc:
            raise ValueError(f"Invalid path '{path}': {exc}") from exc
        return candidate

    def call(
        self,
        command: str = "view",
        path: str = "",
        file_text: str = None,
        old_str: str = None,
        new_str: str = None,
        insert_line: int = None,
        view_range: list = None,
        **kwargs,
    ) -> ToolResult:

        full_path = self._resolve_path(path)

        try:
            if command == "view":
                return self._view(full_path, view_range)
            elif command == "create":
                return self._create(full_path, file_text)
            elif command == "str_replace":
                return self._str_replace(full_path, old_str, new_str)
            elif command == "insert":
                return self._insert(full_path, insert_line, new_str)
            elif command == "undo_edit":
                return self._undo(full_path)
            elif command == "delete":
                return self._delete(full_path)
            else:
                return ToolResult(error=f"Unknown command: {command}")
        except Exception as e:
            return ToolResult(error=f"File operation failed: {str(e)}")

    def _view(self, path: str, view_range=None) -> ToolResult:
        if not os.path.exists(path):
            return ToolResult(error=f"Path does not exist: {path}")

        if os.path.isdir(path):
            entries = []
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                is_dir = os.path.isdir(item_path)
                size = os.path.getsize(item_path) if not is_dir else 0
                entries.append(f"{'[DIR]' if is_dir else '[FILE]'} {item:20} {size:>10} bytes")
            return ToolResult(data="\n".join(entries))

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if view_range and len(view_range) == 2:
            start, end = view_range
            start = max(1, start)
            end = min(total_lines, end) if end != -1 else total_lines
            content_lines = lines[start - 1 : end]
            header = f"--- Viewing {path} (Lines {start}-{end} of {total_lines}) ---"
        else:
            # Smart truncation for large files
            if total_lines > 500:
                content_lines = lines[:250] + ["\n... [TRUNCATED] ...\n"] + lines[-250:]
                header = f"--- Viewing {path} (Truncated: first/last 250 of {total_lines} lines) ---"
            else:
                content_lines = lines
                header = f"--- Viewing {path} ({total_lines} lines) ---"

        numbered = "\n".join(
            f"{i + (start if view_range else 1):6}\t{line.rstrip()}" 
            for i, line in enumerate(content_lines)
        )
        return ToolResult(data=f"{header}\n{numbered}")

    def _delete(self, path: str) -> ToolResult:
        if not os.path.exists(path):
            return ToolResult(error=f"Path not found: {path}")
        if os.path.abspath(path) == os.path.abspath(self.root):
            return ToolResult(error="Refusing to delete project root")
        if os.path.isdir(path) and os.environ.get("NEXUS_ALLOW_DIRECTORY_DELETE", "false").lower() != "true":
            return ToolResult(error="Refusing recursive directory delete without NEXUS_ALLOW_DIRECTORY_DELETE=true")
        snapshot_note, rollback_id = self._snapshot_if_file(path, "file_edit delete")
        baseline_id = self._patch_baseline_if_file(path, "file_edit delete")
        
        # Save to history before deleting? Maybe not for large files.
        # For now, just delete.
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        else:
            os.remove(path)
        patch_note = self._record_patch(baseline_id, path, "file_edit delete", rollback_id)
        return ToolResult(data=f"Successfully deleted: {path}{snapshot_note}{patch_note}")

    def _validate(self, path: str) -> str:
        """[FIDELITY_CHECK]: Performs a structural integrity audit on the file."""
        if path.endswith(".py"):
            import py_compile
            try:
                py_compile.compile(path, doraise=True)
                return " [FIDELITY_PASS]"
            except Exception as e:
                return f" [FIDELITY_FAIL: {str(e)}]"
        elif path.endswith(".json"):
            import json
            try:
                with open(path, "r") as f: json.load(f)
                return " [FIDELITY_PASS]"
            except Exception as e:
                return f" [FIDELITY_FAIL: {str(e)}]"
        return " [FIDELITY_SKIPPED]"

    def _create(self, path: str, file_text: str) -> ToolResult:
        if os.path.exists(path):
            return ToolResult(error=f"File already exists: {path}")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(file_text or "")
        _file_history.add(path, file_text or "")
        status = self._validate(path)
        return ToolResult(data=f"File created: {path}{status}")

    def _str_replace(self, path: str, old_str: str, new_str: str) -> ToolResult:
        if not old_str:
            return ToolResult(error="old_str is required for str_replace")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_str)
        if count == 0:
            return ToolResult(error=f"old_str not found in {path}")
        if count > 1:
            return ToolResult(
                error=f"Multiple ({count}) occurrences found. Be more specific with more context."
            )

        _file_history.add(path, content)
        snapshot_note, rollback_id = self._snapshot_if_file(path, "file_edit str_replace")
        baseline_id = self._patch_baseline_if_file(path, "file_edit str_replace")
        new_content = content.replace(old_str, new_str or "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        status = self._validate(path)
        patch_note = self._record_patch(baseline_id, path, "file_edit str_replace", rollback_id)
        return ToolResult(data=f"Successfully updated {path}{status}{snapshot_note}{patch_note}")

    def _insert(self, path: str, insert_line: int, new_str: str) -> ToolResult:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        _file_history.add(path, content)
        snapshot_note, rollback_id = self._snapshot_if_file(path, "file_edit insert")
        baseline_id = self._patch_baseline_if_file(path, "file_edit insert")
        
        # Ensure insert_line is within bounds
        idx = max(0, min(insert_line, len(lines)))
        new_lines = lines[:idx] + (new_str or "").split("\n") + lines[idx:]
        
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
        status = self._validate(path)
        patch_note = self._record_patch(baseline_id, path, "file_edit insert", rollback_id)
        return ToolResult(data=f"Inserted at line {idx} in {path}{status}{snapshot_note}{patch_note}")

    def _undo(self, path: str) -> ToolResult:
        prev = _file_history.undo(path)
        if prev is None:
            return ToolResult(error=f"No undo history for {path}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(prev)
        return ToolResult(data=f"Undone last edit for: {path}")

    def is_read_only(self, input_data=None):
        if input_data:
            return input_data.get("command") == "view"
        return False

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert", "undo_edit", "delete"]},
                    "path": {"type": "string"},
                    "file_text": {"type": "string", "description": "Full text for 'create'"},
                    "old_str": {"type": "string", "description": "Target string for 'str_replace'"},
                    "new_str": {"type": "string", "description": "Replacement string for 'str_replace' or 'insert'"},
                    "insert_line": {"type": "integer", "description": "Line number for 'insert'"},
                    "view_range": {"type": "array", "items": {"type": "integer"}, "description": "[start, end] lines for 'view'"}
                },
                "required": ["command", "path"]
            }
        }
