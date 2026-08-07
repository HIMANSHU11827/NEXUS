from __future__ import annotations

__version__ = "2.1.0"

import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from nexus.control_plane import create_checklist_plan
from tools.planning.scripts.planning import PlanningTool
from nexus.work_items import reconcile_checklist_work_item


class TaskTool(BaseTool):
    """Task operations backed by the canonical ``todo.md`` plan.

    Planning answers *what should be done*; this tool answers *which checklist
    item is pending or complete*. Both now use the same file and task IDs, so
    the agent cannot create a plan in one store and update tasks in another.
    """

    name = "task"
    description = "Manage checklist tasks in the active planning todo.md"

    _ITEM_RE = re.compile(
        r"^(?P<indent>\s*(?:\d+\.\s+|-\s+))\[(?P<mark>[ xX~>])\]\s+(?P<title>.+?)\s*$"
    )
    _ID_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")

    def _planning(self) -> PlanningTool:
        return PlanningTool(self.root_dir)

    def _read_plan(self) -> str:
        plan = self._planning()._read_plan()
        if plan:
            return plan

        # One-time compatibility read-through for tasks created by the old
        # JSON-only task tool. The next write moves them into todo.md, making
        # planning and task operations share one source of truth.
        legacy_path = Path(self.root_dir or ".") / ".nexus" / "tasks" / "tasks.json"
        if not legacy_path.is_file():
            return ""
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            if not isinstance(legacy, list) or not legacy:
                return ""
            lines = ["TODO LIST", "", "TASK NAME: Migrated task checklist", "PLAN TYPE: Simple", ""]
            for index, item in enumerate(legacy, start=1):
                if not isinstance(item, dict):
                    continue
                task_id = str(item.get("id") or f"task-{index}")
                title = str(item.get("title") or item.get("description") or "Untitled").strip()
                mark = "x" if str(item.get("status", "")).lower() in {"completed", "done"} else " "
                lines.append(f"{index}. [{mark}] [{task_id}] {title}")
            plan = "\n".join(lines)
            if len(lines) > 5:
                self._write_plan(plan)
                return plan
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return ""
        return ""

    def _write_plan(self, plan: str) -> None:
        self._planning()._write_plan(plan)

    def _sync_rows(self, rows: List[Dict[str, Any]], *, session_id: str = "default") -> None:
        if not rows:
            return
        durable_plan = create_checklist_plan(
            root=self.root_dir or ".", session_id=session_id, title="Task checklist",
            goal="Task checklist", rows=rows,
        )
        for row in rows:
            reconcile_checklist_work_item(
                root=self.root_dir or ".",
                session_id=session_id,
                task_id=row["id"],
                title=row["title"],
                checklist_status=row["status"],
                plan_id=durable_plan.plan_id,
            )

    @classmethod
    def _rows(cls, plan: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line_number, line in enumerate(plan.splitlines()):
            match = cls._ITEM_RE.match(line)
            if not match:
                continue
            raw_title = match.group("title").strip()
            id_match = cls._ID_RE.match(raw_title)
            if id_match:
                task_id, title = id_match.group(1), id_match.group(2).strip()
            else:
                task_id, title = f"task-{len(rows) + 1}", raw_title
            mark = match.group("mark").lower()
            status = {"x": "completed", "~": "in_progress", ">": "in_progress"}.get(mark, "pending")
            rows.append({
                "id": task_id,
                "title": title,
                "status": status,
                "line_number": line_number,
                "indent": match.group("indent"),
                "mark": mark,
            })
        return rows

    @classmethod
    def _next_id(cls, rows: List[Dict[str, Any]]) -> str:
        used = {
            int(match.group(1))
            for row in rows
            if (match := re.match(r"task-(\d+)$", str(row.get("id", "")), re.IGNORECASE))
        }
        candidate = 1
        while candidate in used:
            candidate += 1
        return f"task-{candidate}"

    @staticmethod
    def _format_row(row: Dict[str, Any]) -> str:
        mark = {"completed": "x", "in_progress": "~"}.get(row["status"], " ")
        return f"{row['id']}: [{row['status']}] {row['title']}"

    async def execute(
        self,
        action: str,
        id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            operation = (action or "list").strip().lower().replace("-", "_")
            plan = self._read_plan()
            rows = self._rows(plan)
            session_id = str(kwargs.get("session_id") or "default")

            if operation == "list":
                if rows:
                    self._sync_rows(rows, session_id=session_id)
                if not rows:
                    return ToolResult(success=True, output="No tasks in the active plan", metadata={"source": "todo.md"})
                return ToolResult(
                    success=True,
                    output="\n".join(self._format_row(row) for row in rows),
                    metadata={"source": "todo.md", "count": len(rows)},
                )

            if operation == "create":
                task_title = (title or description or "Untitled").strip()
                if not task_title:
                    return ToolResult(success=False, error="Task title is required")
                task_id = str(id or self._next_id(rows)).strip()
                if any(row["id"].lower() == task_id.lower() for row in rows):
                    return ToolResult(success=False, error=f"Task {task_id} already exists")
                if not plan:
                    plan = "TODO LIST\n\nTASK NAME: Task checklist\nPLAN TYPE: Simple\n\n"
                    plan += f"1. [ ] [{task_id}] {task_title}"
                else:
                    line_numbers = [int(value) for value in re.findall(r"^\s*(\d+)\.\s+", plan, re.MULTILINE)]
                    number = (max(line_numbers) if line_numbers else 0) + 1
                    plan = plan.rstrip() + f"\n{number}. [ ] [{task_id}] {task_title}"
                self._write_plan(plan)
                self._sync_rows(self._rows(plan), session_id=session_id)
                return ToolResult(success=True, output=f"Created task: {task_id}", metadata={"source": "todo.md", "task_id": task_id})

            if operation in {"status", "get"}:
                if not str(id or "").strip():
                    return ToolResult(success=False, error="Task id is required for status")
                row = next((item for item in rows if item["id"].lower() == str(id).lower()), None)
                if not row:
                    return ToolResult(success=False, error=f"Task {id} not found in the active plan")
                return ToolResult(success=True, output=self._format_row(row), metadata={"source": "todo.md"})

            if operation in {"update", "delete"} and not str(id or "").strip():
                # Missing optional bookkeeping IDs are safe no-ops. In
                # particular, delete must never broaden into deleting all.
                message = (
                    "Skipped task update: no task id was provided; no task was changed."
                    if operation == "update" else
                    "Skipped task deletion: no task id was provided; no tasks were deleted."
                )
                return ToolResult(success=True, output=message, metadata={"skipped": True, "reason": "missing_id", "action": operation})

            row_index = next((index for index, row in enumerate(rows) if row["id"].lower() == str(id).lower()), None)
            if row_index is None:
                return ToolResult(success=False, error=f"Task {id} not found in the active plan")

            if operation == "delete":
                lines = plan.splitlines()
                del lines[rows[row_index]["line_number"]]
                self._write_plan("\n".join(lines))
                self._sync_rows(self._rows("\n".join(lines)), session_id=session_id)
                return ToolResult(success=True, output=f"Deleted task: {id}", metadata={"source": "todo.md", "task_id": id})

            if operation == "update":
                new_status = str(status or rows[row_index]["status"]).strip().lower()
                if new_status not in {"pending", "in_progress", "completed"}:
                    return ToolResult(success=False, error="Status must be pending, in_progress, or completed")
                new_title = (title or rows[row_index]["title"]).strip()
                mark = {"pending": " ", "in_progress": "~", "completed": "x"}[new_status]
                lines = plan.splitlines()
                indent = rows[row_index]["indent"]
                lines[rows[row_index]["line_number"]] = f"{indent}[{mark}] [{rows[row_index]['id']}] {new_title}"
                self._write_plan("\n".join(lines))
                self._sync_rows(self._rows("\n".join(lines)), session_id=session_id)
                return ToolResult(success=True, output=f"Updated task {id}: [{new_status}] {new_title}", metadata={"source": "todo.md", "task_id": id})

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
