"""V5 Tool Executor - Real tool execution for the V5 loop.

Extracted from ``core.py`` and upgraded to unified-loop parity:
- Commands go through risk scoring, the permission system and the sovereign
  sandbox (unchanged).
- Registry-backed tools now go through a per-call AUDIT first (permission
  policy with context, kernel plugin ``pre_tool_call`` hooks, and the human
  approval broker in ask-mode) - mirroring ``loop._audit_and_approve``.
- Unknown tools are rejected.  Startup/runtime registry discovery is the
  single authority for executable tools, skills, and MCP adapters.
- Provider aliases are CANONICALIZED into the registered NEXUS tools
  (``file_ops``, ``read``, ``write``, ``shell``, ...) like the unified loop.
- Free-text tool calls (inline ``name({...})``, ``<function: name>``,
  ``<function=name>{json}``, dotted ``name.key=value``) are extracted from
  model text so a plan-less model response can still execute tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple

from providers.reliability import redact_secrets


class _TextToolCall:
    """Duck-typed ToolCall shape for text extraction (no circular import).

    Compatible with ``core.ToolCall``, ``paorr_enhanced.ToolCall``
    and anything else that only touches ``name`` / ``params`` / ``call_id``.
    """

    __slots__ = ("name", "params", "call_id", "argument_error", "_denied_reason")

    def __init__(self, name: str, params: Dict[str, Any], call_id: str = "", argument_error: str = ""):
        self.name = name
        self.params = params
        self.call_id = call_id
        self.argument_error = str(argument_error or "")[:2000]
        self._denied_reason = ""


class V5ToolExecutor:
    """Mixin providing real tool execution with security checks."""

    COMMAND_ALIASES = ("bash", "run_command", "terminal", "shell", "execute_command")

    async def _record_tool_feedback(self, call, delta: float) -> None:
        """Record tool outcome without blocking the async execution path."""
        root = str(getattr(self, "root_dir", "") or "").strip()
        if not root:
            return
        try:
            from neural.nerve_center import NexusNerveCenter

            nerve = getattr(self, "_feedback_nerve", None)
            if nerve is None:
                nerve = await asyncio.to_thread(NexusNerveCenter, root)
                self._feedback_nerve = nerve
            await asyncio.to_thread(
                nerve.reinforce,
                "tool_execution",
                str(getattr(call, "name", "unknown") or "unknown"),
                delta,
            )
        except Exception:
            # Feedback must never change tool execution semantics.
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("tool feedback recording unavailable", exc_info=True)

    async def _run_tool(self, call) -> str:
        """Execute a tool and record an auditable success/failure signal.

        When the active run has no deadline (``remaining`` is None) the
        direct-loop callers await the tool without any ``asyncio.wait_for``,
        so a registry tool that hangs between stream items would stall the
        turn forever. Bound that case with a sane default dispatch timeout
        (``NEXUS_TOOL_TIMEOUT``, default 120s). Command aliases are exempt:
        they are already bounded by the sandbox's own execution timeout, so
        the sandbox default and any explicit per-call timeout are preserved.
        When a run deadline exists the caller's remaining-budget timeout
        (``asyncio.wait_for(remaining)``) stays authoritative and this
        wrapper does not add another cap.
        """
        try:
            remaining = None
            control = self._current_run_control()
            remaining = getattr(control, "remaining", None) if control is not None else None
            if remaining is None and str(getattr(call, "name", "") or "") not in self.COMMAND_ALIASES:
                result = await asyncio.wait_for(
                    self._run_tool_impl(call), timeout=self._default_tool_timeout()
                )
            else:
                result = await self._run_tool_impl(call)
        except Exception:
            await self._record_tool_feedback(call, -1.0)
            raise
        await self._record_tool_feedback(call, 1.0)
        return result

    def _default_tool_timeout(self) -> float:
        """Sane fallback tool dispatch timeout when no run deadline is set.

        Overridable via ``NEXUS_TOOL_TIMEOUT`` (seconds). Never raises;
        returns 120.0 when the env value is missing or malformed.
        """
        try:
            return max(1.0, float(os.environ.get("NEXUS_TOOL_TIMEOUT", "120.0")))
        except (TypeError, ValueError):
            return 120.0

    def _current_run_control(self):
        registry = getattr(self, "_run_controls", None)
        current = str(getattr(self, "_current_turn_id", "") or "")
        return registry.get(current) if registry is not None and current else None

    def _remaining_run_budget(self) -> Optional[float]:
        control = self._current_run_control()
        fence = getattr(control, "execution_fence", None) if control is not None else None
        if callable(fence):
            try:
                owns_execution = bool(fence())
            except Exception:
                owns_execution = False
            if not owns_execution:
                registry = getattr(self, "_run_controls", None)
                current = str(getattr(self, "_current_turn_id", "") or "")
                request_cancel = getattr(registry, "request_cancel", None)
                if callable(request_cancel) and current:
                    request_cancel(current, "queue_lease_lost")
                raise asyncio.CancelledError("queue lease ownership was lost")
        remaining = getattr(control, "remaining", None) if control is not None else None
        if remaining is not None and remaining <= 0:
            check_deadline = getattr(self, "_check_deadline", None)
            if callable(check_deadline):
                check_deadline()
            raise asyncio.TimeoutError("V5 run deadline exceeded")
        return remaining

    async def _await_run_budget(self, awaitable):
        """Await one operation while observing the active run's budget/cancel."""
        control = self._current_run_control()
        if control is None:
            return await awaitable
        task = asyncio.ensure_future(awaitable)
        try:
            while not task.done():
                registry = getattr(self, "_run_controls", None)
                current = str(getattr(self, "_current_turn_id", "") or "")
                refresh = getattr(registry, "refresh_cancel", None)
                if callable(refresh) and current:
                    try:
                        refresh(current)
                    except Exception:
                        logger = getattr(self, "logger", None)
                        if logger is not None:
                            logger.debug("could not refresh durable tool cancellation", exc_info=True)
                fence = getattr(control, "execution_fence", None)
                if callable(fence):
                    try:
                        owns_execution = bool(fence())
                    except Exception:
                        owns_execution = False
                    if not owns_execution:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                        raise asyncio.CancelledError("queue lease ownership was lost")
                if control.cancelled:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise asyncio.CancelledError(control.reason or "V5 run cancelled")
                remaining = control.remaining
                if remaining is not None and remaining <= 0:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise asyncio.TimeoutError("V5 run deadline exceeded")
                wait_for = min(0.05, remaining) if remaining is not None else 0.05
                await asyncio.wait({task}, timeout=max(0.001, wait_for))
            return await task
        except BaseException:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            raise

    async def _next_run_stream_item(self, iterator):
        """Read one stream item with a freshly computed run budget."""
        return await self._await_run_budget(iterator.__anext__())

    async def _close_stream(self, iterator) -> None:
        close = getattr(iterator, "aclose", None)
        if callable(close):
            with suppress(Exception):
                await close()

    # ────────────────────────────────────────────────────────────────────────
    # EXECUTION
    # ────────────────────────────────────────────────────────────────────────

    async def _run_tool_impl(self, call) -> str:
        """Resolve, audit and execute a single tool call for real.

        Commands go through risk scoring, the permission system and the
        sovereign sandbox. Registry tools are canonicalized, auto-discovered
        when missing and audited against the permission policy before the
        registry's ``stream_execute`` runs. Raises RuntimeError on failure.
        """
        argument_error = str(getattr(call, "argument_error", "") or "").strip()
        if argument_error:
            error_text = f"Error: invalid arguments for tool '{getattr(call, 'name', 'unknown')}': {argument_error}"
            await self._emit_tool_event(call, status="error", error=error_text)
            raise RuntimeError(error_text)
        call = self._canonicalize_tool_call(call)
        await self._emit_tool_event(call, status="running")
        # Validate queue/run ownership at the last shared boundary before any
        # direct sandbox or registry-backed tool can begin a side effect.
        self._remaining_run_budget()

        # Commands are owned by the process sandbox, not the tool registry.
        if call.name in self.COMMAND_ALIASES:
            cmd = (
                call.params.get("CommandLine")
                or call.params.get("cmd")
                or call.params.get("command")
                or ""
            )
            if not cmd.strip():
                error_text = "Error: empty command"
                await self._emit_tool_event(call, status="failed", error=error_text)
                raise RuntimeError(error_text)

            sandbox = self.runtime.sandbox
            if sandbox is None:
                error_text = "Error: sandbox unavailable"
                await self._emit_tool_event(call, status="failed", error=error_text)
                raise RuntimeError(error_text)

            if self.runtime.risk_scorer is not None:
                assessment = self.runtime.risk_scorer.assess(cmd)
                if assessment.blocked:
                    error_text = (
                        f"Error: command blocked by risk policy: {assessment.summary()}"
                    )
                    await self._emit_tool_event(call, status="blocked", error=error_text)
                    raise RuntimeError(error_text)

            permissions = self.runtime.permissions
            if permissions is None:
                error_text = "Permission system unavailable; command execution is blocked"
                await self._emit_tool_event(call, status="blocked", error=error_text)
                raise RuntimeError(error_text)
            if permissions is not None:
                try:
                    result = permissions.check(
                        call.name,
                        cmd,
                        context=self._permission_context(),
                    )
                except Exception as e:
                    self.logger.warning(f"Permission check failed: {e}")
                    error_text = f"Permission check unavailable: {e}"
                    await self._emit_tool_event(call, status="blocked", error=error_text)
                    raise RuntimeError(error_text) from e
                if result is not None and hasattr(result, "granted") and not result.granted:
                    # ask/APPROVE mode: a command is a first-class tool call, so
                    # route it through the same human-approval broker that
                    # ``_audit_tool_call`` uses for registry tools. On approval
                    # execution continues below (the command re-executes); any
                    # other denial keeps the original hard-deny path unchanged.
                    approved = False
                    if self._result_requires_approval(result):
                        approved = await self._await_human_approval(call.name, cmd)
                    if not approved:
                        reason = getattr(result, "reason", "policy")
                        error_text = f"Permission denied: {reason}"
                        await self._emit_tool_event(call, status="blocked", error=error_text)
                        raise RuntimeError(error_text)

            chunks: List[str] = []
            sequence = 0
            background_param = call.params.get("background")
            if isinstance(background_param, str):
                explicit_background = background_param.strip().lower() in {
                    "1", "true", "yes", "on"
                }
                background_supplied = True
            else:
                explicit_background = bool(background_param) if background_param is not None else False
                background_supplied = background_param is not None
            background = (
                explicit_background
                if background_supplied
                else bool(getattr(sandbox, "should_background_command", lambda _cmd: False)(cmd))
            )
            stream_kwargs = {
                "workdir": call.params.get("cwd") or call.params.get("working_directory"),
            }
            requested_shell = call.params.get("shell")
            if requested_shell:
                stream_kwargs["shell"] = requested_shell
            if background:
                stream_kwargs["background"] = True
            remaining = self._remaining_run_budget()
            if remaining is not None:
                stream_kwargs["timeout"] = max(0.001, remaining)
            self._remaining_run_budget()
            iterator = sandbox.stream_execute(cmd, **stream_kwargs)
            try:
                while True:
                    chunk = await self._next_run_stream_item(iterator)
                    safe_chunk = redact_secrets(chunk)
                    chunks.append(safe_chunk)
                    await self._emit_tool_chunk(call, safe_chunk, sequence)
                    sequence += 1
            except StopAsyncIteration:
                pass
            finally:
                await self._close_stream(iterator)
            result = "".join(chunks)
            exit_code = getattr(sandbox, "last_exit_code", None)
            # Preserve the trusted sandbox exit code for the direct-loop
            # action envelope; returning only text loses verifier identity.
            self._last_tool_exit_code = exit_code
            # A sandbox can fail before a child process starts, so the exit
            # code may be missing. Treat structured sandbox/execution markers
            # as failures too; otherwise a blocked command is fed back as a
            # successful tool result and the model cannot repair it.
            sandbox_failure = any(marker in result for marker in (
                "[SANDBOX_BLOCK]", "[SANDBOX_TIMEOUT]", "[SANDBOX_ERROR]",
                "[EXECUTION_ERROR]",
            ))
            exit_marker = re.search(r"\[EXIT_CODE\]:\s*(-?\d+)", result)
            if exit_marker and exit_code in (None, 0):
                try:
                    exit_code = int(exit_marker.group(1))
                except ValueError:
                    exit_code = -1
            if exit_code not in (None, 0) or sandbox_failure:
                error_text = f"Error: command exited with code {exit_code}.\n{result}"
                await self._emit_tool_event(
                    call, status="error", result=result, error=error_text, exit_code=exit_code
                )
                await self._fire_post_tool_hooks(call, "error", error=error_text)
                await self._mark_tool_lifecycle(call, error=True)
                raise RuntimeError(error_text)
            await self._emit_tool_event(
                call,
                status="done",
                result=result,
                exit_code=exit_code,
                background=background,
            )
            await self._fire_post_tool_hooks(call, "done", result=result)
            await self._mark_tool_lifecycle(call, error=False)
            return result

        # Registry-backed tools: resolve only from the startup/runtime registry,
        # then audit.  A model-selected name must have been advertised in the
        # schema snapshot; importing an unadvertised module after selection
        # would bypass discovery, permissions, and user visibility.
        registry = self.tool_registry
        if registry is None:
            raise RuntimeError("Error: tool registry unavailable")
        tool = None
        try:
            tool = registry.get(call.name)
        except Exception as e:
            self.logger.warning(f"Tool registry lookup failed for '{call.name}': {e}")
        if tool is None:
            available = []
            try:
                available = list(registry.list_tools().keys())
            except Exception:
                pass
            error_text = f"Error: Tool '{call.name}' was not advertised by the active registry. Available: {available}"
            await self._emit_tool_event(call, status="error", error=error_text)
            raise RuntimeError(error_text)

        if not await self._audit_tool_call(call):
            reason = getattr(call, "_denied_reason", "policy")
            error_text = f"Permission denied: {reason}"
            await self._emit_tool_event(call, status="blocked", error=error_text)
            raise RuntimeError(error_text)

        if not await self._confirmation_gate(call):
            error_text = "Error: action requires approval"
            await self._emit_tool_event(call, status="blocked", error=error_text)
            raise RuntimeError(error_text)

        lint_path = call.params.get("path") or call.params.get("filepath")
        edit_snapshot = None
        if call.name in {"modifying", "creating"} and lint_path:
            edit_snapshot = await asyncio.to_thread(
                self._capture_edit_snapshot, lint_path
            )
            if edit_snapshot.get("error"):
                error_text = f"Error: edit snapshot failed: {edit_snapshot['error']}"
                await self._emit_tool_event(call, status="error", error=error_text)
                await self._fire_post_tool_hooks(call, "error", error=error_text)
                await self._mark_tool_lifecycle(call, error=True)
                raise RuntimeError(error_text)
            # This is a preflight check only. The authoritative check happens
            # after the tool writes the candidate content below.
            lint_ok, lint_error = await asyncio.to_thread(
                self._lint_source, edit_snapshot["path"]
            )
            if not lint_ok:
                error_text = f"Error: edit rejected by lint:\n{lint_error}"
                await self._emit_tool_event(call, status="error", result="", error=error_text)
                await self._fire_post_tool_hooks(call, "error", error=error_text)
                await self._mark_tool_lifecycle(call, error=True)
                raise RuntimeError(error_text)

        try:
            from tools.nexus_tools.base_tool import ToolResult
        except Exception:
            ToolResult = None

        chunks: List[str] = []
        sequence = 0
        failed_error = ""
        runtime_context = {
            "work_event_sink": self.runtime.work_event_sink or self.work_event_sink,
            "turn_id": self._current_turn_id,
            "session_id": self.session_id,
            "root": self.root_dir,
            "tool_registry": registry,
            "idempotency_key": str(
                getattr(getattr(self.runtime, "current_turn", None), "metadata", {})
                .get("idempotency_key") or ""
            )[:240],
        }
        control = self._current_run_control()
        remaining = self._remaining_run_budget()
        if control is not None:
            runtime_context["run_control"] = control
            runtime_context["deadline_remaining"] = remaining
        stream_params = {**call.params, "_runtime_context": runtime_context}
        if control is not None:
            stream_params["_cancel_token"] = control.cancel_event
        iterator = registry.stream_execute(call.name, **stream_params)
        try:
            while True:
                try:
                    item = await self._next_run_stream_item(iterator)
                except StopAsyncIteration:
                    break
                if ToolResult is not None and isinstance(item, ToolResult):
                    text = str(item.output or item.error or "")
                    if not item.success:
                        failed_error = redact_secrets(
                            item.error or "Tool execution failed"
                        )[:4000]
                else:
                    text = str(item)
                text = redact_secrets(text)
                if text:
                    chunks.append(text)
                    await self._emit_tool_chunk(
                        call,
                        text,
                        sequence,
                        stream="stderr" if failed_error else "stdout",
                    )
                    sequence += 1
        except Exception as e:
            error_text = f"Error: tool execution failed: {redact_secrets(e)[:4000]}"
            await self._emit_tool_event(call, status="error", error=error_text)
            raise RuntimeError(error_text)
        finally:
            await self._close_stream(iterator)

        result = "".join(chunks)
        if failed_error:
            error_text = f"Error: {failed_error}"
            await self._emit_tool_event(call, status="error", result=result, error=error_text)
            await self._fire_post_tool_hooks(call, "error", error=error_text)
            await self._mark_tool_lifecycle(call, error=True)
            raise RuntimeError(error_text)

        if edit_snapshot is not None:
            post_ok, post_error = await asyncio.to_thread(
                self._lint_source, edit_snapshot["path"]
            )
            if not post_ok:
                rollback_error = await asyncio.to_thread(
                    self._restore_edit_snapshot, edit_snapshot
                )
                error_text = f"Error: edit rejected by post-write lint:\n{post_error}"
                if rollback_error:
                    error_text += f"\nRollback failed: {rollback_error}"
                await self._emit_tool_event(call, status="error", result=result, error=error_text)
                await self._fire_post_tool_hooks(call, "error", error=error_text)
                await self._mark_tool_lifecycle(call, error=True)
                raise RuntimeError(error_text)
        await self._emit_tool_event(call, status="done", result=result)
        await self._fire_post_tool_hooks(call, "done", result=result)
        await self._mark_tool_lifecycle(call, error=False)
        return result

    async def _mark_tool_lifecycle(self, call, *, error: bool) -> None:
        """Record the tool outcome against the lifecycle framework, if any."""
        lc_mark = getattr(self, "_lifecycle_mark", None)
        if not callable(lc_mark):
            return
        try:
            entity = str(getattr(call, "call_id", None) or getattr(call, "name", "?"))
            await lc_mark(
                "tool",
                entity,
                "ERROR" if error else "ACTIVE",
                tool=str(getattr(call, "name", "")),
            )
        except Exception:
            pass

    # ────────────────────────────────────────────────────────────────────────
    # AUDIT (V5: _audit_and_approve)
    # ────────────────────────────────────────────────────────────────────────

    def _permission_context(self) -> Dict[str, Any]:
        return {
            "run_id": self._current_turn_id or self.session_id,
            "turn_id": self._current_turn_id,
            "session_id": self.session_id,
            "surface": "loop_v5",
        }

    async def _audit_tool_call(self, call) -> bool:
        """Check the permission policy for one registry-backed tool call.

        Mirrors ``loop._audit_and_approve`` per call: kernel plugin
        ``pre_tool_call`` hooks fire first, then the permission system decides.
        A ``mode:manual_approval`` refusal becomes a QUESTION for the human
        through the approval broker instead of a silent denial.
        """
        if self.kernel is not None:
            plugins = getattr(self.kernel, "plugins", None)
            if plugins is not None:
                trigger = getattr(plugins, "trigger_hooks", None)
                if callable(trigger):
                    try:
                        hook_results = await trigger("pre_tool_call", [call])
                    except Exception as e:
                        self.logger.warning(f"pre_tool_call hooks failed: {e}")
                    else:
                        # A hook may veto the call by returning a block
                        # directive. These were previously discarded, silently
                        # letting a vetoed tool run — honor them as a hard
                        # denial carrying the hook's reason.
                        for hook_result in hook_results or []:
                            block_reason = self._hook_block_reason(hook_result)
                            if block_reason is not None:
                                setattr(call, "_denied_reason", block_reason)
                                self.logger.warning(
                                    "Tool %s blocked by pre_tool_call hook: %s",
                                    call.name,
                                    block_reason,
                                )
                                return False

        permissions = self.runtime.permissions
        if permissions is None:
            setattr(call, "_denied_reason", "permission system unavailable")
            self.logger.error("Blocking tool %s because the permission system is unavailable", call.name)
            return False
        command = str(
            call.params.get("command")
            or call.params.get("cmd")
            or call.params.get("CommandLine")
            or ""
        )
        action = command if command else str(call.params)
        try:
            result = permissions.check(
                call.name,
                action,
                context=self._permission_context(),
            )
        except Exception as e:
            self.logger.warning(f"Permission check failed for '{call.name}': {e}")
            setattr(call, "_denied_reason", f"permission check unavailable: {e}")
            return False
        if result is None or not hasattr(result, "granted"):
            return True
        if result.granted:
            return True

        # A refusal whose decision context is ask/APPROVE mode becomes a
        # QUESTION for the human through the approval broker instead of a
        # silent denial (see _result_requires_approval).
        if self._result_requires_approval(result):
            approved = await self._await_human_approval(call.name, action)
            if approved:
                # The registry path has a second risk confirmation gate below.
                # Remember this exact call so one human decision cannot turn
                # into a hidden second broker request with no UI event.
                self._remember_approval(call)
                return True
        reason = getattr(result, "reason", "policy")
        setattr(call, "_denied_reason", reason)
        self.logger.warning("Permission denied for %s: %s", call.name, reason)
        return False

    @staticmethod
    def _result_requires_approval(result: Any) -> bool:
        """True when a permission refusal came from ask/APPROVE mode.

        ``PermissionResult`` carries the decision context inside ``.decision``
        (there is no ``source`` attribute on the object itself), so read both
        locations defensively to stay compatible with any check() shape.
        """
        try:
            source = str(getattr(result, "source", "") or "")
            if not source:
                decision = getattr(result, "decision", None) or {}
                source = str(decision.get("source") or "")
            # Only the *pending* ask/APPROVE refusal routes to the broker; a
            # recorded human verdict must never re-open a prompt.
            return source == "mode:manual_approval"
        except Exception:
            return False

    @staticmethod
    def _hook_block_reason(result: Any) -> Optional[str]:
        """Extract a block directive from one ``pre_tool_call`` hook result.

        Accepts both ``{"action": "block"}`` and ``{"block": True}`` shapes and
        falls back to the hook's ``reason``/``message`` for the denial text.
        Returns None when the result carries no block directive, so unrelated
        hook return values are ignored just like before.
        """
        try:
            if not isinstance(result, dict):
                return None
            blocked = result.get("action") == "block" or result.get("block") is True
            if not blocked:
                return None
            reason = result.get("reason") or result.get("message") or "Blocked by plugin hook."
            return str(reason)
        except Exception:
            return None

    async def _await_human_approval(self, tool_name: str, action: str) -> bool:
        """Ask a human to approve one tool call and wait for the answer.

        Emits a ``tool.approval_request`` work event and blocks only this call
        until a decision arrives or the request times out. A timeout or missing
        surface denies, so an unattended session can never auto-approve.
        """
        try:
            from permissions.approval_broker import (
                DECISION_ALLOW,
                DECISION_ALLOW_ALWAYS,
                get_approval_broker,
            )
        except Exception:
            # Unknown risk state must require confirmation. Returning False
            # here means _confirmation_gate interprets the failure as "no
            # confirmation needed" and can execute without a human decision.
            return True

        try:
            broker = get_approval_broker()
            request = broker.open(
                session_id=self.session_id,
                tool_name=tool_name,
                action=action,
                reason="ask-mode approval requested by V5 loop",
                turn_id=self._current_turn_id or "",
                timeout_s=min(300.0, remaining) if (remaining := self._remaining_run_budget()) is not None else 300.0,
            )
        except Exception as e:
            self.logger.warning(f"Approval broker unavailable: {e}")
            return False
        await self._emit_work_event(request.to_event())

        decision = await self._await_run_budget(broker.wait(request.request_id))
        granted = decision in (DECISION_ALLOW, DECISION_ALLOW_ALWAYS)

        if decision == DECISION_ALLOW_ALWAYS:
            try:
                self.runtime.permissions.add_rule(tool_name, "*", granted=True)
            except Exception:
                self.logger.debug("Could not persist allow rule for %s", tool_name)

        await self._emit_work_event({
            "id": request.request_id,
            "event_type": "tool.approval_request",
            "kind": "approval",
            "status": "done" if granted else "failed",
            "request_id": request.request_id,
            "turn_id": self._current_turn_id or "",
            "tool": tool_name,
            "action": action,
            "title": f"{'Approved' if granted else 'Denied'} {tool_name}",
            "target": action,
            "decision": decision,
        })

        # Mirror the human verdict into the permission ledger so the JSONL
        # audit trail shows both the original ask-mode denial and its outcome.
        try:
            permissions = getattr(self.runtime, "permissions", None)
            if permissions is not None and hasattr(permissions, "record_approval"):
                permissions.record_approval(
                    tool_name,
                    action,
                    granted=granted,
                    session_id=self.session_id,
                )
        except Exception:
            self.logger.debug("Could not record approval verdict for %s", tool_name)

        return granted

    # ────────────────────────────────────────────────────────────────────────
    # RISK GATING (V5 roadmap #5 - OpenHands lesson)
    # ────────────────────────────────────────────────────────────────────────

    def _risk_class_for_call(self, call) -> str:
        """Classify one tool call as low/medium/high/critical; never raises.

        Priority order: explicit ``call.risk`` override, destructive
        delete/remove actions, command risk scoring, sensitive-path writes,
        then file-op and search heuristics. Anything unclassifiable defaults
        to "medium" so unexpected actions never silently slip through as low.
        """
        try:
            override = getattr(call, "risk", None)
            if override in {"low", "medium", "high", "critical"}:
                return override
            name = str(getattr(call, "name", "") or "").strip().lower()
            raw_params = getattr(call, "params", None) or {}
            if isinstance(raw_params, str):
                try:
                    raw_params = json.loads(raw_params)
                except json.JSONDecodeError:
                    raw_params = {}
            params = dict(raw_params) if isinstance(raw_params, dict) else {}

            action = str(params.get("action") or "").strip().lower()
            command = str(
                params.get("command")
                or params.get("cmd")
                or params.get("CommandLine")
                or ""
            )
            if name == "deleting" or action in {"delete", "remove"}:
                return "critical"
            lowered_command = command.lower()
            if "rm -rf" in lowered_command or "remove-item -recurse" in lowered_command:
                return "critical"

            if name in {"bash", "shell"} or command:
                return self._score_command_risk(command)

            path = str(params.get("path") or params.get("filepath") or "")
            if path and self._path_is_sensitive(path):
                return "high"

            if name == "modifying":
                return "medium"
            if name in {"creating", "reading"}:
                return "low"
            if (
                "search" in name
                or name.startswith("web_")
                or "browser" in name
                or name in {"grep", "glob", "code_search", "web_search"}
            ):
                return "low"
            return "medium"
        except Exception:
            return "medium"

    def _score_command_risk(self, command: str) -> str:
        """Map the command risk scorer's score onto a risk class."""
        scorer = getattr(getattr(self, "runtime", None), "risk_scorer", None)
        if scorer is None or not callable(getattr(scorer, "assess", None)):
            return "medium"
        try:
            assessment = scorer.assess(command)
            score = int(getattr(assessment, "score", 0) or 0)
        except Exception:
            return "medium"
        if score >= 8:
            return "high"
        if score >= 5:
            return "medium"
        return "low"

    @staticmethod
    def _path_is_sensitive(path: str) -> bool:
        """True when a path targets config, secrets or key material."""
        try:
            lowered = str(path).strip().lower()
            if not lowered:
                return False
            return lowered.endswith((".env", ".pem", ".key")) or any(
                marker in lowered for marker in ("secrets", "credentials")
            )
        except Exception:
            return False

    def _require_confirmation(self, call) -> bool:
        """True only in APPROVE mode for high/critical calls not yet approved.

        Calls whose ``call_id`` was approved earlier this session (kept in
        ``self._approved_calls``) are never re-confirmed. Fail-open on mode
        read failure is NOT acceptable: when the mode is unknown a critical
        call still requires confirmation, because a human-in-the-loop session
        must never silently auto-run destructive actions. Never raises.
        """
        try:
            risk = self._risk_class_for_call(call)
            call_id = getattr(call, "call_id", "") or ""
            if call_id:
                approved = getattr(self, "_approved_calls", None) or {}
                if call_id in approved:
                    return False
            mode = str(self._permission_mode() or "").upper()
            if mode == "APPROVE":
                return risk in {"high", "critical"}
            if not mode:
                return risk == "critical"
            return False
        except Exception:
            # Unknown risk state must require confirmation. Returning False
            # here means _confirmation_gate interprets the failure as "no
            # confirmation needed" and can execute without a human decision.
            return True

    async def _confirmation_gate(self, call) -> bool:
        """Open a human approval request and wait for the decision.

        Fail-closed: no broker, no request id, or any exception denies the
        call. Approvals are remembered per call_id (bounded at 64) so already
        approved calls do not prompt again.
        """
        try:
            if not self._require_confirmation(call):
                return True
            action_text = f"Approve {call.name} on '{self._approval_target(call)}'"
            request_id = self._open_approval(
                call.name,
                action_text,
                session_id=self.session_id,
                timeout=300.0,
            )
            if not request_id:
                return False
            broker = self._approval_broker()
            if broker is None:
                return False
            decision = await self._await_run_budget(broker.wait(request_id))
            if decision in ("allow", "allow_always"):
                self._remember_approval(call)
                return True
            return False
        except Exception as e:
            self.logger.warning(f"Confirmation gate failed for '{call.name}': {e}")
            return False

    def _remember_approval(self, call) -> None:
        """Remember an approved call_id, bounded to the last 64 approvals."""
        try:
            call_id = getattr(call, "call_id", "") or ""
            if not call_id:
                return
            approved = getattr(self, "_approved_calls", None)
            if approved is None:
                approved = {}
                self._approved_calls = approved
            approved[call_id] = True
            while len(approved) > 64:
                try:
                    approved.pop(next(iter(approved)))
                except StopIteration:
                    break
        except Exception:
            pass

    @staticmethod
    def _approval_target(call) -> str:
        """Short human-readable target for a call (local; no events import)."""
        try:
            raw_params = getattr(call, "params", None) or {}
            if isinstance(raw_params, str):
                try:
                    raw_params = json.loads(raw_params)
                except json.JSONDecodeError:
                    raw_params = {}
            params = dict(raw_params) if isinstance(raw_params, dict) else {}
            for key in (
                "path", "filepath", "query", "command", "cmd", "url",
                "target", "name", "action", "server",
            ):
                value = params.get(key)
                if value not in (None, ""):
                    return str(value)
            return str(getattr(call, "name", "work"))
        except Exception:
            return "work"

    # ────────────────────────────────────────────────────────────────────────
    # EDIT QUALITY GATE + WINDOWED ACI (V5 roadmap #8 - SWE-agent lesson)
    # ────────────────────────────────────────────────────────────────────────

    def _lint_source(self, path: str) -> Tuple[bool, str]:
        """Syntax-check a source file before an edit is applied; never raises.

        .py files are checked with ``python -m py_compile``, JS/TS family with
        ``node --check`` when node exists, .json with json.loads. Missing
        files pass (a brand-new file has nothing on disk to lint yet). Returns
        (ok, error_text).
        """
        try:
            if not path or not os.path.isfile(path):
                return True, ""
            ext = os.path.splitext(path)[1].lower()
            if ext == ".py":
                process = subprocess.run(
                    [sys.executable, "-m", "py_compile", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if process.returncode == 0:
                    return True, ""
                return False, (process.stderr or process.stdout or "py_compile failed").strip()
            if ext in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
                node = shutil.which("node")
                if not node:
                    return True, ""
                process = subprocess.run(
                    [node, "--check", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if process.returncode == 0:
                    return True, ""
                return False, (process.stderr or process.stdout or "node --check failed").strip()
            if ext == ".json":
                try:
                    with open(path, encoding="utf-8") as fh:
                        json.loads(fh.read())
                    return True, ""
                except Exception as e:
                    return False, str(e)
            return True, ""
        except Exception as exc:
            # Existing files must fail closed when validation itself cannot
            # run. Returning success here turns an unavailable quality gate
            # into a false edit approval.
            return False, f"lint execution failed: {exc}"

    def _capture_edit_snapshot(self, path: str) -> Dict[str, Any]:
        """Capture an edit target so failed post-write validation can rollback."""
        try:
            raw = os.fspath(path)
            target = os.path.abspath(
                os.path.normpath(raw if os.path.isabs(raw) else os.path.join(self.root_dir, raw))
            )
            if os.path.isfile(target):
                with open(target, "rb") as handle:
                    return {"path": target, "exists": True, "content": handle.read()}
            return {"path": target, "exists": False, "content": b""}
        except Exception as exc:
            return {"path": "", "exists": False, "content": b"", "error": str(exc)}

    @staticmethod
    def _restore_edit_snapshot(snapshot: Dict[str, Any]) -> str:
        """Restore a captured edit target; return an error instead of raising."""
        try:
            target = str(snapshot.get("path") or "")
            if not target:
                return "missing rollback target"
            if snapshot.get("exists"):
                with open(target, "wb") as handle:
                    handle.write(bytes(snapshot.get("content") or b""))
            elif os.path.exists(target):
                os.remove(target)
            return ""
        except Exception as exc:
            return str(exc)

    def _read_windowed(self, path: str, *, window: int = 100, offset: int = 0) -> str:
        """Return a bounded line window of a file with a location header.

        Header is ``#<first>-<last>/#<total>`` (1-based); a trailing ``...``
        marks more lines beyond the window. ``window`` is capped at 400 lines.
        Never raises; returns "" for unreadable or out-of-range input.
        """
        try:
            if not path or not os.path.isfile(path):
                return ""
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            total = len(lines)
            window = max(1, min(int(window or 100), 400))
            offset = max(0, int(offset or 0))
            if offset >= total:
                return ""
            chunk = lines[offset:offset + window]
            if not chunk:
                return ""
            header = f"#{offset + 1}-{offset + len(chunk)}/#{total}"
            body = "".join(chunk)
            if offset + len(chunk) < total:
                body += "\n..."
            return header + "\n" + body
        except Exception:
            return ""

    # ────────────────────────────────────────────────────────────────────────
    # CODE-AS-ACTION MODE (V5 roadmap #17 - smolagents lesson)
    # ────────────────────────────────────────────────────────────────────────

    def _set_code_action_enabled(self, flag: bool) -> bool:
        """Enable/disable code-action mode for this session."""
        try:
            self._code_action_enabled = bool(flag)
            return bool(flag)
        except Exception:
            return False

    def _code_action_active(self) -> bool:
        """True when code-action mode is on; env var wins over the setter."""
        try:
            env = os.environ.get("NEXUS_CODE_ACTION", "")
            if env:
                return str(env).strip().lower() in {"1", "true", "yes", "on"}
            return bool(getattr(self, "_code_action_enabled", False))
        except Exception:
            return False

    def _write_code_action_file(self, code: str) -> str:
        """Write a bounded code-action file under the runtime temp root."""
        root = os.path.realpath(os.path.abspath(str(self.root_dir or os.getcwd())))
        tmp_dir = os.path.realpath(os.path.join(root, ".nexus_v5", "tmp"))
        os.makedirs(tmp_dir, exist_ok=True)
        turn = str(getattr(self, "_current_turn_id", "") or "default")
        safe_turn = re.sub(r"[^A-Za-z0-9_.-]+", "_", turn).strip("._")[:120] or "default"
        file_path = os.path.abspath(os.path.join(tmp_dir, f"code_action_{safe_turn}.py"))
        if os.path.commonpath([tmp_dir, file_path]) != tmp_dir:
            raise ValueError("code-action path escaped the temporary workspace")
        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        return file_path

    async def _execute_code_action(self, code: str, *, workdir: str = "") -> str:
        """Run fenced-python code through the sandbox; never raises.

        Active only when ``_set_code_action_enabled(True)`` was called or
        ``NEXUS_CODE_ACTION=1`` is set (env wins, "0" disables). Code is
        written to ``<root>/.nexus_v5/tmp/code_action_<turn>.py`` and executed
        via ``sandbox.stream_execute`` when available (output capped at 20000
        chars). If no sandbox is active, it fails closed instead of spawning
        an unsandboxed interpreter. Non-zero exits append an "Error:" line.
        """
        try:
            if not self._code_action_active():
                return "Error: code-action mode disabled"
            code = str(code or "")
            if not code.strip():
                return "Error: code-action failed: empty code"
            sandbox = getattr(getattr(self, "runtime", None), "sandbox", None)
            if sandbox is None or not hasattr(sandbox, "stream_execute"):
                return "Error: code-action requires an active sandbox"
            file_path = await asyncio.to_thread(self._write_code_action_file, code)

            chunks: List[str] = []
            stream_kwargs = {"workdir": workdir or self.root_dir}
            remaining = self._remaining_run_budget()
            if remaining is not None:
                stream_kwargs["timeout"] = max(0.001, remaining)
            iterator = sandbox.stream_execute(f'python "{file_path}"', **stream_kwargs)
            try:
                while True:
                    try:
                        chunks.append(
                            redact_secrets(await self._next_run_stream_item(iterator))
                        )
                    except StopAsyncIteration:
                        break
            finally:
                await self._close_stream(iterator)
            output = "".join(chunks)[:20000]
            exit_code = getattr(sandbox, "last_exit_code", None)
            if exit_code not in (None, 0):
                output += f"\nError: code-action exited with code {exit_code}"
            return output
        except Exception as e:
            return f"Error: code-action failed: {redact_secrets(e)[:2000]}"

    # ────────────────────────────────────────────────────────────────────────
    # CANONICALIZATION (V5: _canonicalize_tool_call)
    # ────────────────────────────────────────────────────────────────────────

    def _canonicalize_tool_call(self, call):
        """Translate provider aliases into the registered NEXUS tools."""
        name = str(getattr(call, "name", "") or "").strip().lower()
        raw_params = getattr(call, "params", None) or {}
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except json.JSONDecodeError:
                raw_params = {}
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        call_id = getattr(call, "call_id", "")

        def ps_literal(value: str) -> str:
            return str(value or ".").replace("'", "''")

        if name == "file_ops":
            action = str(params.get("action") or "").strip().lower()
            if action in {"read", "view"}:
                return _TextToolCall("reading", {"path": params.get("path", "")}, call_id)
            if action in {"write", "create"} and "content" in params:
                return _TextToolCall(
                    "creating",
                    {"path": params.get("path", ""), "content": params.get("content", "")},
                    call_id,
                )
            if action in {"edit", "update", "replace"}:
                return _TextToolCall(
                    "modifying",
                    {
                        "path": params.get("path", ""),
                        "old_string": params.get("old_string", ""),
                        "new_string": params.get("new_string", params.get("content", "")),
                    },
                    call_id,
                )
            if action in {"delete", "remove"}:
                return _TextToolCall("deleting", {"path": params.get("path", "")}, call_id)
            if action in {"mkdir", "create"}:
                path = ps_literal(params.get("path", ""))
                return _TextToolCall(
                    "bash",
                    {"command": f'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -LiteralPath \'{path}\'"'},
                    call_id,
                )
            if action == "list":
                path = ps_literal(params.get("path", "."))
                return _TextToolCall(
                    "bash",
                    {"command": f'powershell -NoProfile -Command "Get-ChildItem -Force -LiteralPath \'{path}\'"'},
                    call_id,
                )
        if name in {"read", "read_file", "view"}:
            return _TextToolCall("reading", {"path": params.get("path", params.get("filepath", ""))}, call_id)
        if name in {"write", "write_code", "create"}:
            if "content" in params:
                return _TextToolCall(
                    "creating",
                    {"path": params.get("path", params.get("filepath", "")), "content": params.get("content", "")},
                    call_id,
                )
            path = ps_literal(params.get("path", params.get("filepath", "")))
            return _TextToolCall(
                "bash",
                {"command": f'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -LiteralPath \'{path}\'"'},
                call_id,
            )
        if name in {"edit", "update", "replace"}:
            return _TextToolCall(
                "modifying",
                {
                    "path": params.get("path", params.get("filepath", "")),
                    "old_string": params.get("old_string", ""),
                    "new_string": params.get("new_string", params.get("content", "")),
                },
                call_id,
            )
        if name in {"delete", "remove"}:
            return _TextToolCall("deleting", {"path": params.get("path", params.get("filepath", ""))}, call_id)
        if name == "list":
            path = ps_literal(params.get("path", "."))
            return _TextToolCall(
                "bash",
                {"command": f'powershell -NoProfile -Command "Get-ChildItem -Force -LiteralPath \'{path}\'"'},
                call_id,
            )
        if name == "mkdir":
            path = ps_literal(params.get("path", params.get("filepath", "")))
            return _TextToolCall(
                "bash",
                {"command": f'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -LiteralPath \'{path}\'"'},
                call_id,
            )
        if name in {"shell", "terminal", "execute_command", "run_command"}:
            command = params.get("command") or params.get("cmd") or params.get("input") or ""
            mkdir_match = re.fullmatch(
                r"\s*mkdir\s+(?:-p\s+)?[\"']?([^\"']+?)[\"']?\s*",
                str(command),
                re.IGNORECASE,
            )
            if mkdir_match:
                path = ps_literal(mkdir_match.group(1).strip())
                return _TextToolCall(
                    "bash",
                    {"command": f'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -LiteralPath \'{path}\'"'},
                    call_id,
                )
            return _TextToolCall("bash", {**params, "command": command}, call_id)
        aliases = {
            "search_code": "code_search",
            "web_research": "web_search",
            "search_web": "web_search",
            "run_tests": "test_runner",
        }
        return _TextToolCall(aliases.get(name, name), params, call_id)

    # ────────────────────────────────────────────────────────────────────────
    # FREE-TEXT TOOL CALL EXTRACTION (V5: _extract_tool_calls family)
    # ────────────────────────────────────────────────────────────────────────

    def _extract_tool_calls_from_text(self, text: str) -> List[Any]:
        """Extract tool calls from model text in common provider formats.

        Supports inline ``name({json})``, ``<function=name>{json}``,
        ``<function: name>`` envelopes with ``<param name=.. value=../>`` and
        dotted ``name.key=value`` lines. Results are duck-typed calls; call
        ``_canonicalize_tool_call`` to map aliases onto registered tools.
        """
        calls: List[Any] = []
        if not text:
            return calls
        known = set()
        try:
            if self.tool_registry is not None:
                known = set(self.tool_registry.list_tools().keys())
        except Exception:
            pass
        known |= set(self.COMMAND_ALIASES)
        known |= {
            "reading", "creating", "modifying", "deleting",
            "web_search", "code_search", "git_ops", "test_runner",
            "hive", "deep_research", "file_ops",
        }
        calls.extend(self._extract_inline_tool_calls(text, known))
        calls.extend(self._extract_colon_function_tool_calls(text))
        calls.extend(self._extract_dotted_tool_calls(text, known))
        return calls

    def _extract_inline_tool_calls(self, text: str, known: set) -> List[Any]:
        """``name({...})`` inline calls and ``<function=name>{json}`` envelopes."""
        calls: List[Any] = []
        for match in re.finditer(r"\b([a-zA-Z_]\w*)\(\s*(\{)", text):
            name = match.group(1).lower()
            if name not in known:
                continue
            start = match.start(2)
            try:
                params, consumed = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            tail = text[start + consumed:]
            if isinstance(params, dict) and re.match(r"\s*\)", tail):
                calls.append(_TextToolCall(name, params))
        for match in re.finditer(r"<function=(\w+)>\s*(\{)", text):
            name = match.group(1).lower()
            if name not in known:
                continue
            start = match.start(2)
            try:
                params, _consumed = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(params, dict):
                calls.append(_TextToolCall(name, params))
        return calls

    def _extract_colon_function_tool_calls(self, text: str) -> List[Any]:
        """Provider envelopes such as ``<function: web_search>``.

        Accepts the malformed ``value="text</param>`` form emitted by some
        OpenAI-compatible providers as well as normal quoted values.
        """
        calls: List[Any] = []
        if not text or "<function:" not in text.lower():
            return calls
        function_pattern = re.compile(
            r"<function:\s*([\w.-]+)\s*>([\s\S]*?)(?:</function>|$)",
            re.IGNORECASE,
        )
        param_pattern = re.compile(
            r"<param\s+name=[\"']([^\"']+)[\"']\s+value=[\"']?([\s\S]*?)(?:[\"']?\s*/?>|</param>)",
            re.IGNORECASE,
        )
        for name, body in function_pattern.findall(text):
            params: Dict[str, Any] = {}
            for param_name, raw_value in param_pattern.findall(body):
                params[param_name] = self._coerce_dsml_value(
                    raw_value.strip().strip('"')
                )
            calls.append(_TextToolCall(name.strip(), params))
        return calls

    def _extract_dotted_tool_calls(self, text: str, known: set) -> List[Any]:
        """``name.key = value`` lines, grouped per tool name."""
        calls: List[Any] = []
        pattern = re.compile(
            r"\b([a-zA-Z_]\w*)\.([a-zA-Z_][\w]*)\s*=\s*"
            r"(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|(\{[^{}]*\}|[^\s,;]+))"
        )
        buckets: Dict[str, Dict[str, Any]] = {}
        for match in pattern.finditer(text or ""):
            name = match.group(1).lower()
            if name not in known:
                continue
            key = match.group(2)
            quoted = match.group(3) or match.group(4)
            raw = match.group(5)
            if quoted is not None:
                value: Any = quoted.replace('\\"', '"').replace("\\\\", "\\")
            elif raw is not None:
                value = self._coerce_dsml_value(raw)
            else:
                continue
            buckets.setdefault(name, {})[key] = value
        for name, params in buckets.items():
            calls.append(_TextToolCall(name, params))
        return calls

    @staticmethod
    def _coerce_dsml_value(raw: str) -> Any:
        """Coerce a textual param value into bool/int/float/list/dict/str."""
        value = str(raw).strip()
        if not value:
            return value
        try:
            return json.loads(value)
        except Exception:
            pass
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return value
