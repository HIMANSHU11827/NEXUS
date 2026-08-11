from __future__ import annotations

__version__ = "2.0.0"

import json
import asyncio
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from typing import Any

from tools.nexus_tools.base_tool import BaseTool, ToolResult
from nexus.control_plane import create_checklist_plan
from nexus.work_items import reconcile_checklist_work_item


_PLAN_LOCKS: dict[str, threading.RLock] = {}
_PLAN_LOCKS_GUARD = threading.RLock()


def _todo_path_for_root(root_dir: str | None) -> str:
    root = os.path.abspath(root_dir or os.getcwd())
    workspace = os.path.join(root, "workspace")
    return os.path.join(workspace, "todo.md") if os.path.isdir(workspace) else os.path.join(root, "todo.md")


@contextmanager
def plan_transaction(root_dir: str | None):
    """Serialize plan read/modify/write transactions across threads/processes."""
    todo_path = _todo_path_for_root(root_dir)
    os.makedirs(os.path.dirname(todo_path), exist_ok=True)
    key = os.path.normcase(os.path.abspath(todo_path))
    with _PLAN_LOCKS_GUARD:
        local_lock = _PLAN_LOCKS.setdefault(key, threading.RLock())
    lock_path = f"{todo_path}.lock.sqlite"
    connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
    try:
        with local_lock:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS plan_mutex "
                "(id INTEGER PRIMARY KEY CHECK (id = 1))"
            )
            connection.execute("INSERT OR IGNORE INTO plan_mutex(id) VALUES (1)")
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            finally:
                connection.rollback()
    finally:
        connection.close()


class PlanningTool(BaseTool):
    """Create and maintain one truthful, task-specific todo.md plan."""

    name = "planning"
    description = "Create, update, add, and complete task plans in todo.md"

    async def execute(
        self,
        goal: str = "",
        action: str = "create",
        item: str = "",
        phase: str = "",
        old_text: str = "",
        new_text: str = "",
        plan_spec: Any = None,
        **kwargs,
    ) -> ToolResult:
        """Persist plan/checklist state without blocking the event loop."""
        return await asyncio.to_thread(
            self._execute_sync,
            goal,
            action,
            item,
            phase,
            old_text,
            new_text,
            plan_spec,
            **kwargs,
        )

    def _execute_sync(
        self,
        goal: str = "",
        action: str = "create",
        item: str = "",
        phase: str = "",
        old_text: str = "",
        new_text: str = "",
        plan_spec: Any = None,
        **kwargs,
    ) -> ToolResult:
        with plan_transaction(self.root_dir):
            return self._execute_sync_unlocked(
                goal, action, item, phase, old_text, new_text, plan_spec, **kwargs
            )

    def _execute_sync_unlocked(
        self,
        goal: str = "",
        action: str = "create",
        item: str = "",
        phase: str = "",
        old_text: str = "",
        new_text: str = "",
        plan_spec: Any = None,
        **kwargs,
    ) -> ToolResult:
        try:
            operation = (action or "create").strip().lower().replace("-", "_")
            if operation == "create":
                if not goal or not goal.strip():
                    return ToolResult(success=False, error="Goal is required to create a plan")
                # A plan must come from the active LLM. Never replace a failed
                # model plan with a generic local template.
                plan = self._plan_from_spec(goal.strip(), plan_spec)
                if not plan:
                    return ToolResult(
                        success=False,
                        error="Planning failed: the model did not return a valid task-specific plan",
                    )
                plan = self._ensure_stable_ids(plan, self._read_plan())
                self._write_plan(plan)
                self._sync_work_items(plan, str(kwargs.get("session_id") or "default"))
                return ToolResult(success=True, output=plan, metadata={
                    "file": self._todo_path(),
                    "action": "create",
                    "source": "llm",
                })

            plan = self._read_plan()
            if not plan:
                return ToolResult(success=False, error="No todo.md plan exists yet")

            if operation == "add":
                if not item.strip():
                    return ToolResult(success=False, error="Item is required to add a todo")
                plan = self._add_item(plan, item.strip(), phase.strip())
            elif operation in {"complete", "done"}:
                if not item.strip():
                    return ToolResult(success=False, error="Item is required to mark a todo done")
                plan = self._complete_item(plan, item.strip())
            elif operation == "update":
                if not old_text.strip() or not new_text.strip():
                    return ToolResult(success=False, error="old_text and new_text are required to update a todo")
                plan = self._update_item(plan, old_text.strip(), new_text.strip())
            else:
                return ToolResult(success=False, error=f"Unsupported planning action: {action}")

            plan = self._ensure_stable_ids(plan, self._read_plan())
            self._write_plan(plan)
            self._sync_work_items(plan, str(kwargs.get("session_id") or "default"))
            return ToolResult(success=True, output=plan, metadata={"file": self._todo_path(), "action": operation})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _todo_path(self) -> str:
        if not self.root_dir:
            return "todo.md"
        workspace = os.path.join(self.root_dir, "workspace")
        return os.path.join(workspace, "todo.md") if os.path.isdir(workspace) else os.path.join(self.root_dir, "todo.md")

    def _read_plan(self) -> str:
        path = self._todo_path()
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()

    def _write_plan(self, plan: str) -> None:
        path = self._todo_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            dir=os.path.dirname(os.path.abspath(path)), prefix=".todo-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(plan.rstrip() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
            except OSError:
                pass

    @staticmethod
    def _ensure_stable_ids(plan: str, previous: str = "") -> str:
        prior: dict[str, str] = {}
        for line in (previous or "").splitlines():
            match = re.match(r"^\s*(?:\d+\.\s+|-\s+)\[[ xX~>/]\]\s+\[([^\]]+)\]\s+(.+?)\s*$", line)
            if match:
                prior[match.group(2).strip().lower()] = match.group(1).strip()

        def replace(match: re.Match) -> str:
            prefix, mark, body = match.group(1), match.group(2), match.group(3).strip()
            if re.match(r"^\[[^\]]+\]\s+", body):
                return match.group(0)
            task_id = prior.get(body.lower()) or f"task_{uuid.uuid4().hex[:12]}"
            return f"{prefix}[{mark}] [{task_id}] {body}"

        return re.sub(r"^(\s*(?:\d+\.\s+|-\s+))\[([ xX~>/])\]\s+(.+?)\s*$", replace, plan, flags=re.MULTILINE)

    def _sync_work_items(self, plan: str, session_id: str) -> None:
        rows = []
        for line in plan.splitlines():
            match = re.match(r"^\s*(?:\d+\.\s+|-\s+)\[([ xX~>/])\]\s+\[([^\]]+)\]\s+(.+?)\s*$", line)
            if not match:
                continue
            mark, task_id, title = match.groups()
            status = {"x": "completed", "~": "in_progress", ">": "in_progress"}.get(mark.lower(), "pending")
            rows.append({"id": task_id, "title": title, "status": status})
        if not rows:
            return
        goal_match = re.search(r"^TASK NAME:\s*(.+?)\s*$", plan, flags=re.MULTILINE | re.IGNORECASE)
        goal = goal_match.group(1).strip() if goal_match else "Task checklist"
        durable_plan = create_checklist_plan(
            root=self.root_dir or ".", session_id=session_id, title=goal, goal=goal, rows=rows,
        )
        for row in rows:
            reconcile_checklist_work_item(
                root=self.root_dir or ".", session_id=session_id, task_id=row["id"],
                title=row["title"], checklist_status=row["status"], plan_id=durable_plan.plan_id,
            )

    def _plan_from_spec(self, goal: str, plan_spec: Any) -> str:
        """Validate a model-generated JSON plan before writing it to todo.md."""
        if isinstance(plan_spec, str):
            try:
                plan_spec = json.loads(plan_spec)
            except json.JSONDecodeError:
                return ""
        if not isinstance(plan_spec, dict):
            return ""

        plan_type = str(plan_spec.get("plan_type", "simple")).strip().lower()
        if plan_type == "phased":
            phases = plan_spec.get("phases")
            if not isinstance(phases, list) or not 2 <= len(phases) <= 7:
                return ""
            lines = self._header(goal, "Phased")
            valid_phase_count = 0
            for index, raw_phase in enumerate(phases, start=1):
                if not isinstance(raw_phase, dict):
                    continue
                title = self._clean_plan_line(raw_phase.get("title", ""))
                subgoals = raw_phase.get("subgoals")
                if not title or not isinstance(subgoals, list):
                    continue
                clean_subgoals = [self._clean_plan_line(item) for item in subgoals]
                clean_subgoals = [item for item in clean_subgoals if item][:6]
                if not clean_subgoals:
                    continue
                valid_phase_count += 1
                lines.append(f"PHASE {index}: {title}")
                lines.extend(f"- [ ] {item}" for item in clean_subgoals)
                lines.append("")
            return "\n".join(lines).rstrip() if valid_phase_count >= 2 else ""

        steps = plan_spec.get("steps")
        if not isinstance(steps, list):
            return ""
        clean_steps = [self._clean_plan_line(item) for item in steps]
        clean_steps = [item for item in clean_steps if item][:8]
        if not 3 <= len(clean_steps) <= 8:
            return ""
        lines = self._header(goal, "Simple")
        lines.extend(f"{index}. [ ] {step}" for index, step in enumerate(clean_steps, start=1))
        return "\n".join(lines)

    @staticmethod
    def _clean_plan_line(value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^(?:[-*]|\d+[.)])\s*(?:\[[ xX]\]\s*)?", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:300]

    def _generate_plan(self, goal: str) -> str:
        if self._is_complex(goal):
            return self._generate_phase_plan(goal)
        return self._generate_simple_plan(goal)

    @staticmethod
    def _is_complex(goal: str) -> bool:
        text = goal.lower()
        explicit = ("full", "end-to-end", "end to end", "complex", "large-scale", "platform", "multi-step")
        domains = ("project", "application", "app", "website", "api", "backend", "frontend", "database", "system", "deployment")
        action_words = ("build", "create", "implement", "develop", "refactor", "migrate", "redesign")
        return (
            any(term in text for term in explicit)
            or (sum(term in text for term in domains) >= 2 and any(term in text for term in action_words))
            or (len(text.split()) >= 18 and any(term in text for term in action_words))
        )

    @staticmethod
    def _header(goal: str, plan_type: str) -> list[str]:
        return ["TODO LIST", "", f"TASK NAME: {goal}", f"PLAN TYPE: {plan_type}", ""]

    def _generate_simple_plan(self, goal: str) -> str:
        lines = self._header(goal, "Simple")
        steps = self._simple_steps(goal)
        lines.extend(f"{index}. [ ] {step}" for index, step in enumerate(steps, start=1))
        return "\n".join(lines)

    @staticmethod
    def _simple_steps(goal: str) -> list[str]:
        text = goal.lower()
        if any(word in text for word in ("news", "current", "latest", "search", "research", "headline")):
            return [
                f"Define the live-information target: {goal}",
                "Search current, relevant sources for the requested facts",
                "Confirm dates, source credibility, and agreement between results",
                "Extract only the details needed to answer this request",
                "Deliver a concise answer grounded in the verified results",
            ]
        if any(word in text for word in ("code", "bug", "fix", "implement", "function", "test", "error")):
            return [
                f"Inspect the code and behavior relevant to: {goal}",
                "Identify the smallest correct change and affected files",
                "Implement the change without altering unrelated behavior",
                "Run focused checks for the changed behavior",
                "Review the result and report the verified outcome",
            ]
        if any(word in text for word in ("file", "folder", "document", "image", "pdf", "data")):
            return [
                f"Locate the files needed for: {goal}",
                "Inspect the relevant contents and constraints",
                "Perform the requested file operation",
                "Verify the resulting files and output",
                "Report exactly what was completed",
            ]
        return [
            f"Define the requested outcome: {goal}",
            "Identify the information, tools, or files needed",
            "Carry out the requested work",
            "Verify the result meets the requested outcome",
            "Deliver the completed result with relevant details",
        ]

    def _generate_phase_plan(self, goal: str) -> str:
        lines = self._header(goal, "Phased")
        for index, (name, subgoals) in enumerate(self._phase_steps(goal), start=1):
            lines.append(f"PHASE {index}: {name}")
            lines.extend(f"- [ ] {subgoal}" for subgoal in subgoals)
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _phase_steps(goal: str) -> list[tuple[str, list[str]]]:
        text = goal.lower()
        phases: list[tuple[str, list[str]]] = [
            ("Understand scope", ["Review the request", "Identify constraints and success criteria"]),
            ("Plan the implementation", ["Break work into safe changes", "Choose the required tools and files"]),
        ]
        if any(word in text for word in ("web", "frontend", "ui", "react", "website")):
            phases.append(("Build the interface", ["Implement the requested screens and interactions", "Check responsive layout and usability"]))
        if any(word in text for word in ("api", "backend", "server", "database", "system")):
            phases.append(("Build the runtime", ["Implement the required logic", "Connect data and service boundaries"]))
        phases.extend([
            ("Verify the work", ["Run focused checks", "Fix any failures found"]),
            ("Complete the task", ["Review the final result", "Report what changed"]),
        ])
        return phases

    @staticmethod
    def _plan_type(plan: str) -> str:
        match = re.search(r"^PLAN TYPE:\s*(.+)$", plan, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip().lower() if match else "simple"

    def _add_item(self, plan: str, item: str, phase: str) -> str:
        if self._plan_type(plan) != "phased":
            numbers = [int(value) for value in re.findall(r"^(\d+)\.\s+", plan, re.MULTILINE)]
            return plan.rstrip() + f"\n{(max(numbers) if numbers else 0) + 1}. [ ] {item}"

        lines = plan.splitlines()
        target = phase.lower()
        insert_at = len(lines)
        for index, line in enumerate(lines):
            if line.upper().startswith("PHASE ") and (not target or target in line.lower()):
                insert_at = index + 1
                while insert_at < len(lines) and not lines[insert_at].upper().startswith("PHASE "):
                    insert_at += 1
                break
        lines.insert(insert_at, f"- [ ] {item}")
        return "\n".join(lines)

    @staticmethod
    def _complete_item(plan: str, item: str) -> str:
        pattern = re.compile(r"(\[ \]\s+)([^\n]+)", re.IGNORECASE)
        found = False

        def replace(match: re.Match) -> str:
            nonlocal found
            if not found and item.lower() in match.group(2).lower():
                found = True
                return "[x] " + match.group(2)
            return match.group(0)

        updated = pattern.sub(replace, plan)
        if not found:
            raise ValueError(f"Todo item not found: {item}")
        return updated

    @staticmethod
    def _update_item(plan: str, old_text: str, new_text: str) -> str:
        if old_text.lower() not in plan.lower():
            raise ValueError(f"Todo item not found: {old_text}")
        return re.sub(re.escape(old_text), new_text, plan, count=1, flags=re.IGNORECASE)
