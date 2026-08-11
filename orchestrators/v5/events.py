"""V5 Event Emitter - Canonical work-event emission for the V5 loop.

Extracted from ``core.py`` so the core class stays an orchestration
skeleton. Payload shapes are identical to the unified loop (``orchestrators/loop.py``)
so the GUI/TUI frontends consume V5 events exactly like V1 events.
"""

from __future__ import annotations

import inspect
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers.reliability import redact_secrets


EVENT_SUMMARY_LIMIT = 128


def _safe_event_text(value: Any, limit: int = 160) -> str:
    """Bound and redact identity text; never retain event payload content."""
    return redact_secrets(str(value or ""))[:limit]


def stable_event_id(event: Dict[str, Any], *, ordinal: int = 0, run_id: str = "") -> str:
    """Return an opaque stable ID without hashing or copying event payloads.

    Existing producer IDs remain compatible.  For malformed/anonymous events,
    derive an ID from bounded envelope fields and emission order only.
    """
    explicit = event.get("event_id") or event.get("id")
    if explicit:
        return _safe_event_text(explicit)
    fields = "|".join(
        (
            _safe_event_text(run_id or event.get("run_id") or event.get("turn_id")),
            _safe_event_text(event.get("event_type") or event.get("type")),
            _safe_event_text(event.get("status")),
            _safe_event_text(event.get("parent_id")),
            _safe_event_text(event.get("tool") or event.get("name")),
            str(max(0, int(ordinal))),
        )
    ).encode("utf-8", "replace")
    return "v5evt_" + hashlib.sha256(fields).hexdigest()[:32]


def summarize_work_event(event: Any, *, ordinal: int = 0, run_id: str = "") -> Dict[str, Any]:
    """Create an identity-only, bounded event summary.

    Deliberately excludes ``payload``, output/result fields, commands, paths,
    titles, and errors.  This is suitable for terminal evidence persistence.
    """
    item = event if isinstance(event, dict) else {}
    summary: Dict[str, Any] = {
        "event_id": stable_event_id(item, ordinal=ordinal, run_id=run_id),
        "event_type": _safe_event_text(item.get("event_id") and item.get("event_type") or item.get("event_type") or item.get("type"), 80),
        "status": _safe_event_text(item.get("status"), 32),
        "parent_id": _safe_event_text(item.get("parent_id"), 160),
        "tool": _safe_event_text(item.get("related_tool") or item.get("tool") or item.get("name"), 120),
        "kind": _safe_event_text(item.get("kind"), 40),
        "part_type": _safe_event_text(item.get("part_type"), 40),
        "visibility": _safe_event_text(item.get("visibility"), 16),
    }
    for key in ("sequence", "exit_code"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            summary[key] = value
    duration = item.get("duration_ms")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        summary["duration_ms"] = round(max(0.0, float(duration)), 3)
    return summary


def summarize_work_events(events: Any, *, limit: int = EVENT_SUMMARY_LIMIT,
                          run_id: str = "") -> Dict[str, Any]:
    """Summarize only the last bounded set of canonical work events."""
    source = events if isinstance(events, list) else []
    bounded_limit = max(1, min(int(limit), EVENT_SUMMARY_LIMIT))
    start = max(0, len(source) - bounded_limit)
    summaries = [
        summarize_work_event(event, ordinal=index, run_id=run_id)
        for index, event in enumerate(source[start:], start=start)
        if isinstance(event, dict)
    ]
    return {
        "schema_version": 1,
        "count": len(source),
        "truncated": len(source) > bounded_limit,
        "events": summaries,
    }


class V5EventEmitter:
    """Mixin providing canonical event emission to the work event sink."""

    def canonical_event_summaries(self, limit: int = 128) -> List[Dict[str, Any]]:
        """Return bounded event identity for durable evidence, without payloads."""
        try:
            cap = max(1, min(int(limit), 256))
        except (TypeError, ValueError):
            cap = 128
        events = getattr(self, "_stream_events", [])
        summaries: List[Dict[str, Any]] = []
        for sequence, event in enumerate(events[-cap:], start=max(0, len(events) - cap)):
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id") or event.get("id")
            event_type = event.get("type") or event.get("event_type")
            if not event_id and not event_type:
                continue
            item: Dict[str, Any] = {
                "event_id": str(event_id or "")[:160],
                "type": str(event_type or "")[:80],
                "status": str(event.get("status") or "")[:32],
                "sequence": sequence,
                "parent_id": str(event.get("parent_id") or "")[:160],
                "related_tool": str(event.get("related_tool") or event.get("tool") or "")[:120],
            }
            if isinstance(event.get("error"), dict):
                item["has_error"] = bool(event["error"])
            summaries.append(item)
        return summaries

    async def _emit_work_event(self, payload: Dict[str, Any]) -> None:
        """Deliver a canonical work event to the sink and stream queue.

        The sink call is fully guarded so a broken GUI sink can never break
        the loop.
        """
        # A few compatibility/test emitters provide class-level defaults;
        # never let one emitter instance share its mutable event buffers with
        # another instance.
        if "_stream_events" not in getattr(self, "__dict__", {}):
            self._stream_events = []
        if "_event_summary_turn_id" not in getattr(self, "__dict__", {}):
            self._event_summary_turn_id = ""
            self._event_summary_events = []
            self._event_summary_count = 0
        # Keep the live queue backward-compatible, but retain only an
        # identity-only summary for terminal evidence.  The summary buffer is
        # reset when a new turn becomes active and never contains raw payloads.
        turn_key = str(getattr(self, "_current_turn_id", "") or getattr(self, "session_id", ""))
        if getattr(self, "_event_summary_turn_id", "") != turn_key:
            self._event_summary_turn_id = turn_key
            self._event_summary_events = []
            self._event_summary_count = 0
        summary_events = getattr(self, "_event_summary_events", [])
        self._event_summary_count = int(getattr(self, "_event_summary_count", 0)) + 1
        summary_events.append(
            summarize_work_event(
                payload,
                ordinal=self._event_summary_count - 1,
                run_id=turn_key,
            )
        )
        del summary_events[:-EVENT_SUMMARY_LIMIT]
        self._event_summary_events = summary_events
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
                # Close the tool-telemetry loop: every terminal tool outcome is
                # recorded into the registry's execution history so that
                # success-rate / latency / error stats are actually populated
                # (record_execution previously had NO production caller, so the
                # whole get_tool_stats subsystem was dead telemetry). This must
                # never fail the tool event itself -- telemetry is best-effort.
                status_for_stats = {
                    "done": "ok",
                    "error": "error",
                    "failed": "error",
                    "blocked": "blocked",
                }.get(status, status)
                registry = getattr(self, "tool_registry", None)
                if registry is not None and callable(getattr(registry, "record_execution", None)):
                    try:
                        registry.record_execution(
                            name=str(call.name or ""),
                            params=getattr(call, "params", None) or {},
                            result=result or error,
                            duration_ms=payload["duration_ms"],
                            status=status_for_stats,
                        )
                    except Exception:
                        pass
        await self._emit_work_event(payload)
        # A successful file mutation invalidates the durable verifier state
        # for this workspace/session. Reads do not make an old verdict stale.
        if kind == "file" and status not in ("running", "queued") and not error:
            action = str(call.params.get("action") or "").lower()
            name = str(call.name or "").lower()
            if name in {"modifying", "creating", "deleting", "write", "create", "delete", "remove"} \
                    or action in {"write", "create", "edit", "update", "delete", "remove", "mkdir"}:
                try:
                    from .verification_state import VerifierStateStore

                    path = call.params.get("path") or call.params.get("filepath")
                    root_dir = str(getattr(self, "root_dir", "") or os.getcwd())
                    VerifierStateStore(Path(root_dir) / ".nexus_v5" / "verifier_state.json").mark_stale(
                        str(getattr(self, "session_id", "default") or "default"), root_dir, [path]
                    )
                except Exception:
                    pass

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
        safe_payload = dict(payload or {})
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
            "payload": safe_payload,
            "visibility": "public",
        }
        terminal_summary = self._terminal_event_summary()
        terminal_summary["events"].append(
            summarize_work_event(
                event,
                ordinal=terminal_summary["count"],
                run_id=str(getattr(self, "_event_summary_turn_id", "") or ""),
            )
        )
        terminal_summary["count"] += 1
        if len(terminal_summary["events"]) > EVENT_SUMMARY_LIMIT:
            terminal_summary["events"] = terminal_summary["events"][-EVENT_SUMMARY_LIMIT:]
        terminal_summary["truncated"] = terminal_summary["count"] > len(terminal_summary["events"])
        safe_payload["event_summary"] = terminal_summary
        event["payload"] = safe_payload
        if error:
            event["error"] = {"message": error}
        await self._emit_work_event(event)
        try:
            if callable(getattr(self, "_log_event", None)):
                self._log_event("run.finished", status, payload)
        except Exception:
            pass

    def _terminal_event_summary(self) -> Dict[str, Any]:
        """Return the bounded identity summary captured for the active turn."""
        summary = summarize_work_events(
            getattr(self, "_event_summary_events", []),
            run_id=str(getattr(self, "_event_summary_turn_id", "") or ""),
        )
        count = int(getattr(self, "_event_summary_count", summary["count"]))
        summary["count"] = count
        summary["truncated"] = count > len(summary["events"])
        return summary

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
