"""
NEXUS TASK MANAGER — Claude Code Task system adapted for Python.
Supports: local_bash, local_agent, remote_agent task types with status tracking.
"""

import json
import os
import time
import uuid
import threading
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from utils.singleton import ThreadSafeSingleton


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class TaskType(Enum):
    LOCAL_BASH = "local_bash"
    LOCAL_AGENT = "local_agent"
    REMOTE_AGENT = "remote_agent"
    WORKFLOW = "workflow"


class Task:
    """A single task with status tracking and output capture."""

    def __init__(
        self,
        task_id: str,
        task_type: TaskType,
        description: str,
        command: Callable = None,
        **kwargs,
    ):
        self.id = task_id
        self.type = task_type
        self.description = description
        self.status = TaskStatus.PENDING
        self.command = command
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.output: List[str] = []
        self.metadata = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "status": self.status.value,
            "result": self.result[:500] if self.result else None,
            "error": self.error,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": (self.end_time - self.start_time)
            if self.end_time and self.start_time
            else None,
        }


class TaskManager(ThreadSafeSingleton):
    """Manages concurrent task execution with status tracking."""

    _initialized = False

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: Dict[str, Task] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def generate_id(self, task_type: TaskType) -> str:
        prefix = {
            "local_bash": "b",
            "local_agent": "a",
            "remote_agent": "r",
            "workflow": "w",
        }
        return f"{prefix.get(task_type.value, 'x')}{uuid.uuid4().hex[:8]}"

    def create_task(
        self, task_type: TaskType, description: str, command: Callable = None, **kwargs
    ) -> Task:
        task_id = self.generate_id(task_type)
        task = Task(task_id, task_type, description, command, **kwargs)
        self._tasks[task_id] = task
        return task

    def run_task(self, task: Task, *args, **kwargs) -> str:
        """Execute a task synchronously."""
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        try:
            if task.command:
                result = task.command(*args, **kwargs)
                task.result = str(result)
            task.status = TaskStatus.COMPLETED
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
        task.end_time = time.time()
        return task.result or task.error or "Done"

    def run_task_async(self, task: Task, *args, **kwargs):
        """Execute a task asynchronously in a background thread."""

        def _run():
            self.run_task(task, *args, **kwargs)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        self._threads[task.id] = thread

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def kill_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.KILLED
            task.end_time = time.time()
            return True
        return False

    def list_tasks(self, status_filter: TaskStatus = None) -> List[Dict[str, Any]]:
        tasks = self._tasks.values()
        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]
        return [t.to_dict() for t in tasks]

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._tasks)
        by_status = {}
        for task in self._tasks.values():
            s = task.status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {"total": total, "by_status": by_status}
