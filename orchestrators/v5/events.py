"""V5 Event Emitter - Canonical work-event emission for the V5 loop.

Extracted from ``core.py`` so the core class stays an orchestration
skeleton. Payload shapes are identical to the unified loop (``orchestrators/loop.py``)
so the GUI/TUI frontends consume V5 events exactly like V1 events.
"""

from __future__ import annotations

import inspect
import os
import re
import time
from typing import Any, Dict, List, Optional


class V5EventEmitter:
    """Mixin providing canonical event emission to the work event sink."""

    async def _emit_work_event(self, payload: Dict[str, Any]) -> None:
        """Deliver a canonical work event to the sink and stream queue.

        The sink call is fully guarded so a broken GUI sink can never break
        the loop.
        """
        self._stream_events.append(payload)
        sink = self.runtime.work_event_sink or self.work_event_sink
        if not sink:
            return
        try:
            if inspect.iscoroutinefunction(sink):
                await sink(payload)
            else:
                result = sink(payload)
                if inspect.isawaitable(result):
                    await result
        except Exception as e:
            self.logger.debug(f"work_event_sink failed: {e}")

    async def _emit_runtime_event(
        self,
        event_type: str,
        title: str,
        status: str,
        *,
        event_id: str,
        parent_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        error: str = "",
        visibility: str = "public",
    ) -> None:
        """Central producer for canonical run/message lifecycle events."""
        event_payload = dict(payload or {})
        # Task identity is opt-in so callers that do not associate a run with
        # a WorkItem retain the historical payload shape exactly.
        if task_id:
            event_payload["task_id"] = str(task_id)
        event: Dict[str, Any] = {
            "id": event_id,
            "event_type": event_type,
            "run_id": self._current_turn_id or self.session_id,
            "turn_id": self._current_turn_id,
            "kind": event_type.split(".", 1)[0],
            "title": title,
            "action": title,
            "status": status,
            "parent_id": parent_id,
            "payload": event_payload,
            "visibility": visibility if visibility in {"public", "internal"} else "internal",
        }
        if error:
            event["error"] = {"message": error}
        event["part_type"] = self._infer_part_type(event_type)
        await self._emit_work_event(event)
        try:
            if callable(getattr(self, "_log_event", None)):
                self._log_event(event_type, status, payload)
        except Exception:
            pass

    async def _emit_tool_event(
        self,
        call,
        *,
        status: str,
        result: str = "",
        error: str = "",
        exit_code: Optional[int] = None,
    ) -> None:
        """Publish tool lifecycle events with the canonical work-event shape."""
        kind = self._work_kind_for_call(call.name, call.params)
        target = self._work_target_for_call(call.name, call.params)
        payload: Dict[str, Any] = {
            "id": f"work_{self._current_turn_id or self.session_id}_{call.call_id}",
            "turn_id": self._current_turn_id,
            "tool": call.name,
            "name": call.name,
            "kind": kind,
            "action": self._work_action_for_call(kind, call.name, call.params),
            "target": target,
            "status": status,
            "visibility": "public",
        }
        if kind == "command":
            payload["command"] = str(
                call.params.get("CommandLine")
                or call.params.get("cmd")
                or call.params.get("command")
                or target
            )
            payload["cwd"] = str(
                call.params.get("cwd") or call.params.get("working_directory") or self.root_dir
            )
        if kind == "file":
            payload["path"] = str(call.params.get("path") or call.params.get("filepath") or target)
        if kind == "search":
            payload["query"] = str(call.params.get("query") or target)
        if kind == "mcp":
            server = str(call.params.get("server") or call.params.get("mcp_server") or "MCP")
            mcp_tool = str(
                call.params.get("tool")
                or call.params.get("tool_name")
                or call.params.get("name")
                or call.params.get("action")
                or call.name
            )
            payload["server"] = server
            payload["mcp_tool"] = mcp_tool
            payload["target"] = f"{server} • {mcp_tool}"
        if result:
            payload["result"] = result[:20000]
            payload["output"] = result[:20000]
            if kind == "search":
                payload["preview"] = result[:20000]
                payload["sources"] = list(
                    dict.fromkeys(re.findall(r"https?://[^\s)\]]+", result))
                )[:20]
        if error:
            payload["stderr"] = error[:20000]
            payload["result"] = error[:20000]
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        payload["part_type"] = "tool-call" if status in ("running", "queued") else "tool-result"
        if status in ("running", "queued"):
            self._tool_started_at.setdefault(call.call_id, time.time())
            payload["start_time"] = self._tool_started_at[call.call_id]
        else:
            started_at = self._tool_started_at.pop(call.call_id, None)
            if started_at:
                payload["start_time"] = started_at
                end_time = time.time()
                payload["end_time"] = end_time
                payload["duration_ms"] = max(0.0, (end_time - started_at) * 1000.0)
        await self._emit_work_event(payload)

    async def _emit_tool_chunk(
        self,
        call,
        text: str,
        sequence: int,
        stream: str = "stdout",
    ) -> None:
        """Emit append-only tool output without waiting for tool completion."""
        if not text:
            return
        kind = self._work_kind_for_call(call.name, call.params)
        chunk_size = max(1, int(os.environ.get("NEXUS_TOOL_STREAM_CHARS", "256")))
        value = str(text)
        for part_index, chunk in enumerate(
            value[index:index + chunk_size] for index in range(0, len(value), chunk_size)
        ):
            await self._emit_work_event({
                "id": f"work_{self._current_turn_id or self.session_id}_{call.call_id}",
                "turn_id": self._current_turn_id,
                "tool": call.name,
                "name": call.name,
                "kind": kind,
                "action": self._work_action_for_call(kind, call.name, call.params),
                "target": self._work_target_for_call(call.name, call.params),
                "status": "running",
                "stream": stream,
                "sequence": (sequence * 100000) + part_index,
                "append": True,
                "chunk": chunk,
                "output": chunk,
                "part_type": "tool-chunk",
                "start_time": self._tool_started_at.get(call.call_id),
                "visibility": "public",
            })

    async def _emit_stage_event(
        self,
        stage: str,
        action: str,
        target: str = "",
        status: str = "running",
        *,
        items: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Publish safe execution telemetry without exposing private reasoning."""
        payload: Dict[str, Any] = {
            "id": f"stage_{self._current_turn_id or self.session_id}_{stage}",
            "turn_id": self._current_turn_id,
            "kind": "provider" if stage == "inference" else "test" if stage == "verification" else "task",
            "type": "stage",
            "part_type": "phase",
            "stage": stage,
            "action": action,
            "target": target,
            "status": status,
            "visibility": "public" if stage == "planning" else "internal",
        }
        if items:
            payload["items"] = items
            payload["preview"] = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
            payload["result"] = payload["preview"]
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if status in ("running", "queued"):
            self._stage_started_at.setdefault(stage, time.time())
            payload["start_time"] = self._stage_started_at[stage]
        else:
            started_at = self._stage_started_at.pop(stage, None)
            if started_at:
                payload["start_time"] = started_at
                end_time = time.time()
                payload["end_time"] = end_time
                payload["duration_ms"] = max(0.0, (end_time - started_at) * 1000.0)
        await self._emit_work_event(payload)

    async def _emit_plan_event(
        self,
        status: str,
        *,
        plan_id: str = "",
        goal: str = "",
        step_index: Optional[int] = None,
        total: Optional[int] = None,
        description: str = "",
        steps: Optional[List[str]] = None,
        error: str = "",
    ) -> None:
        """Publish a live plan update as a canonical ``plan.updated`` event.

        Roadmap #2 (Manus/Devin/Gemini plan-mode): surfaces render a live,
        per-step checklist from these events. Step descriptions are rendered
        as ``[{"index": i, "description": d}]`` so frontends never need to
        know the planner internals.
        """
        payload: Dict[str, Any] = {
            "plan_id": plan_id or "",
            "goal": goal or "",
        }
        if step_index is not None:
            payload["step_index"] = int(step_index)
        if total is not None:
            payload["total"] = int(total)
        if description:
            payload["description"] = description
        if steps:
            payload["steps"] = [
                {"index": index, "description": str(step)}
                for index, step in enumerate(steps, start=1)
            ]
        base = f"plan_{self._current_turn_id or self.session_id}"
        event: Dict[str, Any] = {
            "id": f"{base}_{plan_id}" if plan_id else base,
            "event_type": "plan.updated",
            "run_id": self._current_turn_id or self.session_id,
            "turn_id": self._current_turn_id,
            "kind": "plan",
            "part_type": "plan",
            "title": f"Plan {status}",
            "action": description or "plan",
            "status": status,
            "payload": payload,
            "visibility": "public",
        }
        if error:
            event["error"] = {"message": error}
        await self._emit_work_event(event)
        try:
            if callable(getattr(self, "_log_event", None)):
                self._log_event("plan.updated", status, payload)
        except Exception:
            pass

    async def _emit_run_finished(
        self,
        status: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> None:
        """Publish run completion telemetry as a canonical ``run.finished`` event.

        Roadmap #22: budget/cost accounting (``cost``, ``tokens``,
        ``duration_ms``, ``attempts``) is carried verbatim in the payload so
        callers control the exact telemetry shape.
        """
        event: Dict[str, Any] = {
            "id": f"run_{self._current_turn_id or self.session_id}_finished",
            "event_type": "run.finished",
            "run_id": self._current_turn_id or self.session_id,
            "turn_id": self._current_turn_id,
            "kind": "run",
            "part_type": "run",
            "title": "Run finished",
            "action": "run",
            "status": status,
            "payload": payload or {},
            "visibility": "public",
        }
        if error:
            event["error"] = {"message": error}
        await self._emit_work_event(event)
        try:
            if callable(getattr(self, "_log_event", None)):
                self._log_event("run.finished", status, payload)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # WORK EVENT CLASSIFICATION HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _infer_part_type(self, event_type: str) -> str:
        """Derive a typed-part discriminant from the canonical event type."""
        base = str(event_type or "").split(".", 1)[0].lower()
        known = {
            "run", "message", "tool", "plan", "phase", "test",
            "file", "search", "command", "subagent", "skill", "memory", "progress",
        }
        if base in known:
            return base
        return "other"

    def _work_kind_for_call(self, name: str, params: Dict[str, Any]) -> str:
        normalized = str(name or "").lower()
        if normalized in ("bash", "run_command", "terminal", "shell"):
            return "command"
        if "search" in normalized or normalized in {"web_search", "code_search"}:
            return "search"
        if "mcp" in normalized:
            return "mcp"
        if "browser" in normalized:
            return "browser"
        if "provider" in normalized:
            return "provider"
        if "plugin" in normalized:
            return "plugin"
        if "skill" in normalized:
            return "skill"
        if "hive" in normalized or "agent" in normalized or "worker" in normalized:
            return "hive"
        if any(key in params for key in ("path", "filepath", "old_string", "new_string", "content")):
            return "file"
        if normalized in {"reading", "creating", "modifying", "deleting", "read_file", "write_code"}:
            return "file"
        return "tool"

    def _work_target_for_call(self, name: str, params: Dict[str, Any]) -> str:
        for key in (
            "path", "filepath", "query", "command", "cmd", "url", "pattern",
            "target", "name", "action", "problem", "server"
        ):
            value = params.get(key)
            if value not in (None, ""):
                return str(value)
        return str(name or "work")

    def _work_action_for_call(self, kind: str, name: str, params: Dict[str, Any]) -> str:
        action_name = str(params.get("action") or "").lower()
        normalized_name = str(name or "").lower()
        if kind == "search":
            if normalized_name == "code_search":
                return "Code search"
            if normalized_name in {"grep", "glob"}:
                return "Search files"
            return "Web search"
        if kind == "command":
            return "Run command"
        if kind == "mcp":
            return "Use MCP"
        if kind == "browser":
            return "Browser"
        if kind == "provider":
            return "Check provider"
        if kind == "plugin":
            return "Use plugin"
        if kind == "skill":
            return "Use skill"
        if kind == "hive":
            return "Delegate task"
        if kind == "file":
            if action_name in {"read", "view"} or name in {"reading", "read_file"}:
                return "Read file"
            if action_name in {"write", "create", "mkdir"} or name in {"creating", "write_code"}:
                return "Create file"
            if action_name in {"delete", "remove"} or name == "deleting":
                return "Delete file"
            if action_name in {"edit", "update", "replace"} or name == "modifying":
                return "Edit file"
            return "Edit file"
        return "Use tool"
