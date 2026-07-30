"""Compatibility shell for the historical ``python -m nexus --shell`` path.

The Ink TUI is the primary interface, but keeping this small adapter avoids
breaking scripts and integrations that import the old Rich shell API.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from typing import Any

from rich.console import Console

console = Console()


class TaskTracker:
    _tasks: list[dict[str, Any]] = []

    @classmethod
    def create(cls, prompt: str) -> str:
        task_id = str(uuid.uuid4())
        cls._tasks.append({"id": task_id, "prompt": prompt, "status": "running"})
        return task_id

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return list(cls._tasks)


class NexusShell:
    def __init__(self, brain: Any | None = None) -> None:
        self._brain = brain
        self._pending_agent_prompt: str | None = None
        self._pending_task_id: str | None = None

    def _run_bash(self, command: str) -> int:
        console.print(f"Command started: {command}")
        root = getattr(self._brain, "root", os.getcwd())
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            console.print(f"Command failed to start: {exc}")
            return 1
        if completed.stdout:
            console.print(completed.stdout.rstrip())
        if completed.stderr:
            console.print(completed.stderr.rstrip(), style="red")
        console.print(f"Command completed · exit code {completed.returncode}")
        return completed.returncode

    def _handle_slash(self, value: str) -> bool:
        commands = {
            "/verify": "Verify the current project changes and report actionable failures.",
            "/test": "Run the relevant project tests and report actionable failures.",
        }
        prompt = commands.get(value.strip().split(maxsplit=1)[0])
        if prompt is None:
            return False
        self._pending_agent_prompt = prompt
        self._pending_task_id = TaskTracker.create(prompt)
        console.print(f"Queued task {self._pending_task_id}: {prompt}")
        return True

    @staticmethod
    def _render_event(event: dict[str, Any]) -> None:
        visibility = event.get("visibility") or event.get("payload", {}).get("visibility")
        if visibility == "internal":
            return
        related = event.get("related_command") or event.get("target")
        if related:
            console.print(f"$ {related}")
        details = []
        if event.get("status"):
            details.append(str(event["status"]))
        if event.get("exit_code") is not None:
            details.append(f"exit {event['exit_code']}")
        if event.get("duration_ms") is not None:
            details.append(f"{event['duration_ms']}ms")
        if details:
            console.print(" · ".join(details))

    async def _stream_response(self, prompt: str):
        text_parts: list[str] = []
        interrupted = False
        files: list[Any] = []
        tools: list[Any] = []
        if self._brain is None:
            return "", False, files, tools
        try:
            async for item in self._brain.stream_run(prompt):
                kind = item.get("type") if isinstance(item, dict) else None
                if kind == "content":
                    text_parts.append(str(item.get("data", "")))
                elif kind == "status":
                    console.print(str(item.get("data", "")).strip("[]"))
                elif kind == "tools_discovered":
                    tools.extend(item.get("tool_calls", []))
                    console.print("Tools:")
                    for call in item.get("tool_calls", []):
                        name = call.get("name", "tool")
                        command = call.get("arguments", {}).get("command")
                        console.print(f"- {name}" + (f": {command}" if command else ""))
                elif kind == "work_event":
                    event = item.get("event", item)
                    if isinstance(event, dict):
                        self._render_event(event)
                elif kind == "file":
                    files.append(item)
                elif kind == "error":
                    console.print(str(item.get("data", "")), style="red")
        except (asyncio.CancelledError, KeyboardInterrupt):
            interrupted = True
        return "".join(text_parts), interrupted, files, tools


__all__ = ["NexusShell", "TaskTracker", "console"]
