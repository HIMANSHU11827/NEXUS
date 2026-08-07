"""V5Hive — sub-agent (hive) integration for the V5 loop.

V5 with ``orchestrators/loop.py`` ``_maybe_spawn_hive`` (lines
3013-3055) and ``_evolve_hive_feedback`` (lines 3057-3073): when the
``NEXUS_HIVE`` env flag is enabled, complex tasks are decomposed into
persona'd subtasks, run as parallel ``NexusHiveEngine`` sub-agents, and the
consolidated result is folded into the perceived context as a
``[HIVE_RESULT]`` block.  Like V1, hive is strictly opt-in and augments the
main loop — it never replaces it, and every failure is ignored so the loop
never breaks.

This mixin is dependency-free at import time: it imports nothing from
``core`` or any other ``orchestrators.v5`` module (avoiding circular
imports); the hive engine and provider factory are imported lazily inside
methods, mirroring the V1 loop's own lazy ``providers.factory`` import.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# PERSISTED SUB-AGENT STATE (lightweight, pure stdlib, never raises)
# ─────────────────────────────────────────────────────────────────────
# Append-only JSONL at ``~/.nexus/hive/subagents.jsonl``.  Each line is a
# state record ``{id, status, role, parent, started_at, ...}``; reloading
# keeps the LAST line per id (latest status) so a restart surfaces the
# prior process's sub-agents.  The path honors ``_v5_hive_state_file`` on a
# host (used by tests) and defaults to ``~/.nexus/hive/subagents.jsonl``.
_HIVE_STATE_DIR = os.path.join(os.path.expanduser("~"), ".nexus", "hive")
_HIVE_STATE_FILE = os.path.join(_HIVE_STATE_DIR, "subagents.jsonl")

# Result-envelope marker produced by ``_inject_hive_context`` when a hive
# result is folded into the perceived context (v5 convention).  Note: the
# engine (hive/engine.py) does NOT emit this marker itself — consolidation
# returns plain text — so the wrapper is what constructs the envelope.
_HIVE_RESULT_MARKER = "[HIVE_RESULT]"

# States a persisted sub-agent may move through.
_HIVE_STATUS_FLOW = ("spawned", "running", "succeeded", "failed", "timeout", "cancelled")


def load_persisted_subagent_states(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Read persisted sub-agent state records (last line per id wins).

    Pure stdlib and guaranteed not to raise: any IO / JSON problem returns
    ``{}`` so callers can always degrade softly.
    """
    path = path or _HIVE_STATE_FILE
    states: Dict[str, Dict[str, Any]] = {}
    try:
        if not os.path.isfile(path):
            return states
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if isinstance(record, dict) and record.get("id"):
                    states[str(record["id"])] = dict(record)
    except Exception:
        return {}
    return states


# Loaded once at module init so a restart can show the prior sub-agents
# even before any new spawn (satisfies "load on module init").
_PERSISTED_SUBAGENT_STATES: Dict[str, Dict[str, Any]] = load_persisted_subagent_states()


class V5Hive:
    """Sub-agent (hive) integration mixin for the V5 loop.

    Expected attributes when mixed into ``NexusLoopV5`` (all duck-typed,
    every access guarded — the loop must never break):
    - ``self.root`` - str root directory of the project (hive workspace
      feedback is written under ``root/workspace/hive``).
    - ``self.session_id`` - id used for the hive feedback filename.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self.kernel`` - may be None or a lazy kernel exposing
      ``_get_or_init(key, factory)`` (and ``.plugins``); when present it is
      preferred as the source of the cached ``NexusHiveEngine``.
    - ``self.tool_registry`` - optional ToolRegistry passed to spawned
      sub-agents so they can call real tools.
    - ``self._emit_runtime_event(event_type, title, status, event_id=None,
      payload=None)`` - async canonical event producer.
    """

    # ─────────────────────────────────────────────────────────────────────
    # ENABLE / ENGINE / LLM ACCESS (all defensive)
    # ─────────────────────────────────────────────────────────────────────

    def _hive_log(self) -> logging.Logger:
        """Return the loop logger when mixed in, else the module logger."""
        return getattr(self, "logger", None) or logger

    def _hive_enabled(self) -> bool:
        """True when ``NEXUS_HIVE`` env is ``1``/``true``/``yes`` (opt-in).

        Defaults to disabled — V5 (``loop.py`` line 180) with the
        V1 accepted values narrowed to the documented three.
        """
        try:
            value = str(os.environ.get("NEXUS_HIVE", "0") or "0").lower()
            return value in ("1", "true", "yes")
        except Exception:
            return False

    def _hive_engine(self) -> Optional[Any]:
        """Lazy ``NexusHiveEngine``, cached on ``self._v5_hive_engine``.

        Prefers the kernel-owned engine via ``kernel._get_or_init("hive",
        lambda: NexusHiveEngine(self.root))`` (V5); falls back to a
        fresh engine otherwise.  Returns None on any failure so callers can
        safely skip hive work.
        """
        try:
            cached = getattr(self, "_v5_hive_engine", None)
            if cached is not None:
                return cached
            from hive import NexusHiveEngine

            engine: Any = None
            kernel = getattr(self, "kernel", None)
            getter = getattr(kernel, "_get_or_init", None)
            if callable(getter):
                try:
                    engine = getter(
                        "hive", lambda: NexusHiveEngine(getattr(self, "root_dir", ""))
                    )
                except Exception:
                    engine = None
            if engine is None:
                engine = NexusHiveEngine(getattr(self, "root_dir", ""))
            self._v5_hive_engine = engine
            return engine
        except Exception as e:
            self._hive_log().warning(f"[HIVE] engine unavailable: {e}")
            return None

    def _hive_llm_call(self) -> Callable[[List[Dict[str, str]]], str]:
        """Return a sync ``_llm(messages) -> str`` callable for the engine.

        Uses the configured provider factory, including local/offline policy,
        rather than hard-coding a cloud provider. Any provider failure returns
        an empty result so Hive reports the real failed sub-agent.
        """
        def _llm(messages: List[Dict[str, str]]) -> str:
            try:
                from providers.factory import NexusProviderFactory

                factory = NexusProviderFactory()
                provider = factory.get_provider()
                if provider is None:
                    return ""
                if not hasattr(provider, "generate"):
                    return ""
                try:
                    out = provider.generate(messages=messages)
                except TypeError:
                    out = provider.generate(
                        messages[-1].get("content", ""),
                        messages[0].get("content", ""),
                        None,
                    )
                text = str(out or "")
                if text.startswith("Error:") or text.startswith("[PROVIDER_ERROR]"):
                    return ""
                return text
            except Exception:
                return ""

        return _llm

    # ─────────────────────────────────────────────────────────────────────
    # SPAWN + CONSOLIDATE (V5: orchestrators/loop.py:3013-3055)
    # ─────────────────────────────────────────────────────────────────────

    def _effective_hive_timeout(self, default: float) -> float:
        """Cap hive work by the active parent run's remaining budget.

        A hive timeout used to be independent from the parent deadline, so a
        short-lived run could still spend the full default timeout waiting for
        sub-agents.  Keep the existing standalone timeout when no run control
        is active, but make nested work inherit the parent's monotonic budget.
        """
        timeout = max(0.001, float(default))
        registry = getattr(self, "_run_controls", None)
        turn_id = str(getattr(self, "_current_turn_id", "") or "")
        control = registry.get(turn_id) if registry is not None and turn_id else None
        remaining = getattr(control, "remaining", None) if control is not None else None
        if remaining is not None:
            if remaining <= 0:
                check_deadline = getattr(self, "_check_deadline", None)
                if callable(check_deadline):
                    check_deadline()
                raise asyncio.TimeoutError("V5 run deadline exceeded")
            timeout = min(timeout, float(remaining))
        return max(0.001, timeout)

    async def _maybe_spawn_hive(
        self,
        task_desc: str,
        force: bool = False,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[str]:
        """Decompose ``task_desc``, run persona'd sub-agents, consolidate.

        Enforces a real sub-agent timeout (``timeout_seconds``, default from
        ``hive_timeout_seconds``/``NEXUS_HIVE_TIMEOUT``, 120s) around the
        spawn+consolidate call via ``asyncio.wait_for``.  On expiry the
        spawned hive is cancelled through the engine's ``cancel_hive``, the
        persisted states move to ``timeout``, and the current turn is marked
        failed with reason ``timeout``.  When the awaiting parent task is
        cancelled, the hive is cancelled first and the cancellation is then
        surfaced (``raise``).  Returns the consolidated hive text (or None
        when hive is disabled, decomposition produced nothing, or anything
        failed — mirroring V1's "hive spawn failed (ignored)" warning).
        Never raises.
        """
        if not self._hive_enabled() and not force:
            return None
        if timeout_seconds is None:
            timeout_seconds = self._hive_default_timeout()
        try:
            timeout_seconds = self._effective_hive_timeout(timeout_seconds)
            engine = self._hive_engine()
            if engine is None:
                return None
            try:
                engine.set_tool_registry(getattr(self, "tool_registry", None))
            except Exception:
                pass

            llm = self._hive_llm_call()
            try:
                engine.set_llm_call(llm)
            except Exception:
                pass

            subs: List[Tuple[str, str]] = await engine.decompose_task(task_desc, llm)
            if not subs:
                return None

            spawn_state: Dict[str, Any] = {}

            async def _spawn_and_consolidate() -> str:
                sub_id, _agents = await engine.spawn_hive([(t, p) for t, p in subs])
                spawn_state["hive_id"] = str(sub_id or "")
                self._hive_remember_spawn(sub_id, _agents)
                return await engine.consolidate_hive(
                    sub_id, timeout=timeout_seconds, llm_call=llm
                )

            try:
                consolidated = await asyncio.wait_for(
                    _spawn_and_consolidate(), timeout=timeout_seconds
                )
            except asyncio.CancelledError:
                # Parent cancellation: propagate to the sub-agents before
                # surfacing the cancellation.
                hive_id = spawn_state.get("hive_id", "")
                if hive_id:
                    await self._hive_cancel_group(hive_id, reason="cancelled")
                raise
            except (TimeoutError, asyncio.TimeoutError):
                hive_id = spawn_state.get("hive_id", "")
                if hive_id:
                    await self._hive_cancel_group(hive_id, reason="timeout")
                await self._hive_mark_turn_failed("timeout")
                self._hive_log().warning(
                    "[HIVE] sub-agent timeout after %.0fs; hive %s cancelled (ignored)",
                    timeout_seconds,
                    hive_id or "?",
                )
                return None

            hive_id = spawn_state.get("hive_id", "")
            if consolidated:
                self._hive_mark_group_done(hive_id, status="succeeded")
                emitter = getattr(self, "_emit_runtime_event", None)
                if callable(emitter):
                    try:
                        await emitter(
                            "hive.done",
                            f"Hive completed {len(subs)} sub-agents",
                            "success",
                            event_id=f"hive_{hive_id}",
                            payload={"subtasks": len(subs)},
                        )
                    except Exception as e:
                        self._hive_log().debug(
                            "[HIVE] hive.done event failed (ignored): %s", e
                        )
            else:
                self._hive_mark_group_done(
                    hive_id, status="failed", reason="empty consolidation"
                )
            return consolidated or None
        except Exception as e:
            self._hive_log().warning("hive spawn failed (ignored): %s", e)
            return None

    async def _inject_hive_context(self, perceived) -> None:
        """Turn-wiring entry: fold hive output into ``perceived.context_summary``.

        Only runs when hive is enabled and ``perceived`` exposes
        ``context_summary``; the task is read from ``perceived.original_input``.
        The consolidated result is appended as a ``[HIVE_RESULT]`` block
        (hard-capped at 6000 chars) joined to any existing summary with a
        blank line.  Never raises.
        """
        try:
            if not self._hive_enabled():
                return
            if perceived is None:
                return
            if not hasattr(perceived, "context_summary"):
                return
            task_desc = str(getattr(perceived, "original_input", "") or "")
            if not task_desc:
                return
            decision = getattr(perceived, "metadata", {}) or {}
            text = await self._maybe_spawn_hive(
                task_desc,
                force=bool(decision.get("hive_required", False)),
            )
            if not text:
                return
            ok, reason, payload = self._hive_validate_envelope(text)
            if not ok:
                # Invalid / empty sub-agent output: mark the turn failed with
                # reason, keep a subagent_untrusted note, and do NOT inject
                # the raw text into the main context.
                await self._hive_mark_turn_failed(
                    reason or "invalid sub-agent result envelope",
                    subagent_untrusted=True,
                )
                self._hive_log().info(
                    "[HIVE] rejected sub-agent result (%s); raw text not injected", reason
                )
                return
            block = f"{_HIVE_RESULT_MARKER}:\n{payload[:6000]}"
            current = getattr(perceived, "context_summary", None)
            if current:
                setattr(perceived, "context_summary", f"{current}\n\n{block}")
            else:
                setattr(perceived, "context_summary", block)
            self._hive_log().info("[HIVE] injected consolidated hive context")
        except Exception as e:
            self._hive_log().warning(f"[HIVE] failed to inject hive context: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # FEEDBACK (V5: orchestrators/loop.py:3057-3073)
    # ─────────────────────────────────────────────────────────────────────

    async def _evolve_hive_feedback(self, messages: List[Dict[str, str]]) -> None:
        """Persist per-session hive worker feedback for ARCHITECT review.

        When ``root/workspace/hive`` exists, writes
        ``feedback_{session_id}.json`` with session id, assistant turn count,
        and timestamp.  Never raises.
        """
        try:
            hive_dir = os.path.join(self.root, "workspace", "hive")
            if not os.path.isdir(hive_dir):
                return
            feedback: Dict[str, Any] = {
                "session_id": self.session_id,
                "turns": len(
                    [m for m in messages if m.get("role") == "assistant"]
                ),
                "timestamp": time.time(),
            }
            fb_path = os.path.join(hive_dir, f"feedback_{self.session_id}.json")
            with open(fb_path, "w", encoding="utf-8") as f:
                json.dump(feedback, f, indent=2)
        except Exception as e:
            self._hive_log().warning(f"[HIVE] failed to write hive feedback: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # PERSISTED SUB-AGENT STATES + RESULT VALIDATION + CANCELLATION
    #
    # New-path safety net: every helper is guarded and never raises.  Any
    # unexpected exception degrades to the legacy behavior for that step.
    # ─────────────────────────────────────────────────────────────────────

    def _hive_default_timeout(self) -> float:
        """Return the sub-agent timeout in seconds (default 120).

        Honors an instance ``hive_timeout_seconds`` attribute, then the
        ``NEXUS_HIVE_TIMEOUT`` env var, then 120.  Guarded and always > 0.
        """
        try:
            value = getattr(self, "hive_timeout_seconds", None)
            if value is None:
                value = os.environ.get("NEXUS_HIVE_TIMEOUT", "120")
            seconds = float(value)
            return seconds if seconds > 0 else 120.0
        except Exception:
            return 120.0

    def _hive_state_file(self) -> str:
        """Path of the persisted sub-agent state (overrideable for tests)."""
        override = getattr(self, "_v5_hive_state_file", None)
        return str(override) if override else _HIVE_STATE_FILE

    def _hive_load_subagent_states(self) -> Dict[str, Dict[str, Any]]:
        """Load persisted sub-agent states, cached per host (last line wins).

        On first access (i.e. mixin/loop init in a fresh process) this shows
        the prior process's sub-agents, satisfying the restart contract.
        """
        cached = getattr(self, "_v5_subagent_states", None)
        if cached is None:
            cached = load_persisted_subagent_states(self._hive_state_file())
            self._v5_subagent_states = cached
        return cached

    def _hive_reload_subagent_states(self) -> Dict[str, Dict[str, Any]]:
        """Drop the cache and re-read the persisted state file."""
        try:
            cached = load_persisted_subagent_states(self._hive_state_file())
            self._v5_subagent_states = cached
            return cached
        except Exception:
            return self._hive_load_subagent_states()

    def _hive_persist_subagent_state(self, record: Dict[str, Any]) -> None:
        """Append one state record to the JSONL file.  Never raises on IO."""
        try:
            if not isinstance(record.get("id"), str) or not record["id"]:
                return
            path = self._hive_state_file()
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            self._hive_log().debug("[HIVE] persisted state write failed (ignored): %s", e)

    def _hive_update_subagent_state(self, sub_id: str, status: str, **extra: Any) -> None:
        """Persist a state transition for one sub-agent (spawned→running→...)."""
        try:
            states = self._hive_load_subagent_states()
            record = dict(states.get(str(sub_id), {}))
            record["id"] = str(sub_id)
            record["status"] = str(status or "running")
            record["updated_at"] = time.time()
            record.update(extra)
            states[str(sub_id)] = record
            self._hive_persist_subagent_state(record)
        except Exception as e:
            self._hive_log().debug("[HIVE] state update failed (ignored): %s", e)

    def _hive_groups(self) -> Dict[str, Dict[str, Any]]:
        """In-memory ``hive_id -> {"agents": [...], "status": ...}`` registry."""
        groups = getattr(self, "_v5_hive_groups", None)
        if groups is None:
            groups = {}
            self._v5_hive_groups = groups
        return groups

    def _hive_remember_spawn(self, hive_id: str, agents: List[Any]) -> None:
        """Track a spawned hive and persist a ``running`` state per agent."""
        try:
            hive_id = str(hive_id or "")
            if not hive_id:
                return
            groups = self._hive_groups()
            group = groups.setdefault(hive_id, {"agents": [], "status": "running"})
            now = time.time()
            for agent in agents or []:
                sub_id = str(getattr(agent, "agent_id", "") or "")
                if not sub_id:
                    continue
                if sub_id not in group["agents"]:
                    group["agents"].append(sub_id)
                self._hive_update_subagent_state(
                    sub_id,
                    status="running",
                    role=str(getattr(agent, "persona", "WORKER") or "WORKER"),
                    parent=hive_id,
                    started_at=float(getattr(agent, "started_at", 0) or 0) or now,
                )
        except Exception as e:
            self._hive_log().debug("[HIVE] spawn tracking failed (ignored): %s", e)

    def _hive_active_subagent_states(self) -> List[Dict[str, Any]]:
        """Persisted states still in-flight (spawned/running)."""
        active: List[Dict[str, Any]] = []
        for record in self._hive_load_subagent_states().values():
            if str(record.get("status", "")).lower() in ("spawned", "running"):
                active.append(dict(record))
        return active

    def _hive_mark_group_done(
        self, hive_id: str, status: str = "succeeded", **extra: Any
    ) -> None:
        """Move every agent of a hive to a terminal state (never raises)."""
        try:
            for sub_id in self._hive_groups().get(str(hive_id), {}).get("agents", []):
                self._hive_update_subagent_state(sub_id, status=status, **extra)
        except Exception as e:
            self._hive_log().debug(
                "[HIVE] group completion marking failed (ignored): %s", e
            )

    def _hive_mark_groups_failed(self, reason: str) -> None:
        """Mark all tracked sub-agents failed (timeout/cancelled passthrough)."""
        try:
            for _, group in list(self._hive_groups().items()):
                status = "failed"
                if reason in ("timeout", "cancelled"):
                    status = reason
                for sub_id in group.get("agents", []):
                    self._hive_update_subagent_state(
                        sub_id, status=status, reason=reason
                    )
        except Exception as e:
            self._hive_log().debug(
                "[HIVE] group failure marking failed (ignored): %s", e
            )

    async def _hive_cancel_group(self, hive_id: str, reason: str = "cancelled") -> None:
        """Cancel one spawned hive via the engine and persist terminal states."""
        try:
            engine = self._hive_engine()
            cancel = getattr(engine, "cancel_hive", None) if engine is not None else None
            if callable(cancel):
                try:
                    await cancel(str(hive_id))
                except Exception as e:
                    self._hive_log().debug(
                        "[HIVE] cancel hive %s failed (ignored): %s", hive_id, e
                    )
            status = "failed"
            if reason in ("timeout", "cancelled"):
                status = reason
            for sub_id in self._hive_groups().get(str(hive_id), {}).get("agents", []):
                self._hive_update_subagent_state(sub_id, status=status, reason=reason)
            # Honor prior-process members of the same hive (restart case).
            for record in self._hive_active_subagent_states():
                if str(record.get("parent") or "") == str(hive_id):
                    self._hive_update_subagent_state(
                        str(record.get("id") or ""), status=status, reason=reason
                    )
        except Exception as e:
            self._hive_log().warning(
                f"[HIVE] cancel hive {hive_id} failed (ignored): {e}"
            )

    async def _hive_cancel_active(self, reason: str = "cancelled") -> int:
        """Propagate a parent cancellation to every active spawned sub-agent.

        Calls the engine's ``cancel_hive`` for each active id found in the
        status map (in-memory groups plus persisted spawned/running records)
        and marks the members ``cancelled``.  Returns the number of hives
        cancelled.  Never raises.
        """
        cancelled_hives = 0
        try:
            engine = self._hive_engine()
            cancel = getattr(engine, "cancel_hive", None) if engine is not None else None
            seen: set[str] = set()

            def _mark_cancelled(group: Dict[str, Any]) -> None:
                for sub_id in group.get("agents", []):
                    self._hive_update_subagent_state(
                        sub_id, status="cancelled", reason=reason
                    )

            for hive_id, group in list(self._hive_groups().items()):
                if hive_id in seen:
                    continue
                if callable(cancel):
                    try:
                        await cancel(str(hive_id))
                    except Exception as e:
                        self._hive_log().debug(
                            "[HIVE] cancel hive %s failed (ignored): %s", hive_id, e
                        )
                _mark_cancelled(group)
                seen.add(hive_id)
                cancelled_hives += 1

            # Persisted states from a prior process that are still active.
            for record in self._hive_active_subagent_states():
                sub_id = str(record.get("id") or "")
                hive_id = str(record.get("parent") or "")
                if not sub_id:
                    continue
                if hive_id and hive_id != sub_id and hive_id not in seen:
                    if callable(cancel):
                        try:
                            await cancel(hive_id)
                        except Exception as e:
                            self._hive_log().debug(
                                "[HIVE] cancel hive %s failed (ignored): %s",
                                hive_id,
                                e,
                            )
                    seen.add(hive_id)
                    cancelled_hives += 1
                self._hive_update_subagent_state(
                    sub_id, status="cancelled", reason=reason
                )
            return cancelled_hives
        except Exception as e:
            self._hive_log().warning(
                f"[HIVE] cancel propagation failed (ignored): {e}"
            )
            return cancelled_hives

    def _hive_validate_envelope(self, envelope: str) -> Tuple[bool, str, str]:
        """Validate a sub-agent result envelope before injection.

        Returns ``(ok, reason, payload)`` where ``payload`` is the stripped,
        safe text to inject.  Untagged raw output (the engine's concat/LLM
        fallback) is accepted as-is for backward compatibility; a
        ``[HIVE_RESULT]``-tagged envelope is parsed and must carry a non-empty
        ``data``/``result`` (or any non-empty payload) value.  Any unexpected
        validation exception degrades to the legacy behavior (accept the raw
        envelope) so the main loop never breaks.
        """
        try:
            raw = str(envelope or "")
            if not raw.strip():
                return False, "empty sub-agent result", ""
            payload = raw.strip()
            if _HIVE_RESULT_MARKER in payload:
                after = payload.split(_HIVE_RESULT_MARKER, 1)[-1].strip()
                after = re.sub(r"^\s*:\s*", "", after).strip()
                payload = after
                parsed = None
                try:
                    parsed = json.loads(payload) if payload else None
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    value = parsed.get(
                        "data", parsed.get("result", parsed.get("output", ""))
                    )
                    if isinstance(value, str):
                        value = value.strip()
                    if value in (None, "", [], {}):
                        return False, "empty [HIVE_RESULT] payload", payload
                    payload = str(value).strip()
                if not payload:
                    return False, "empty [HIVE_RESULT] payload", ""
            return True, "", payload
        except Exception as e:
            self._hive_log().debug(
                "[HIVE] envelope validation degraded to legacy: %s", e
            )
            return True, "", str(envelope or "")

    async def _hive_mark_turn_failed(self, reason: str, **extra: Any) -> bool:
        """Record a hive failure on the current turn.  Never raises.

        Stores a ``subagent_untrusted`` note (True for rejected envelopes),
        marks any tracked sub-agents failed, emits a best-effort
        ``hive.failed`` runtime event, and duck-typed marks the turn object
        failed when the loop exposes a hook.  Returns whether recorded.
        """
        try:
            turn_id = str(getattr(self, "_current_turn_id", "") or "")
            record: Dict[str, Any] = {
                "status": "failed",
                "reason": reason,
                "turn_id": turn_id,
                "subagent_untrusted": bool(extra.pop("subagent_untrusted", False)),
            }
            record.update(extra)
            setattr(self, "_v5_hive_turn_failure", record)
            self._hive_mark_groups_failed(reason)

            emitter = getattr(self, "_emit_runtime_event", None)
            if callable(emitter):
                try:
                    result = emitter(
                        "hive.failed",
                        f"Hive turn failed: {reason}",
                        "failed",
                        event_id=f"hive_turn_failure_{turn_id or uuid.uuid4().hex[:8]}",
                        payload=record,
                    )
                    if inspect.isawaitable(result):
                        await result
                except Exception as e:
                    self._hive_log().debug("[HIVE] failed to emit hive.failed: %s", e)

            # Best-effort duck-typed turn marking hooks.
            setter = getattr(self, "_set_turn_failed", None) or getattr(
                self, "mark_turn_failed", None
            )
            if callable(setter):
                try:
                    result = setter(reason)
                    if inspect.isawaitable(result):
                        await result
                except Exception as e:
                    self._hive_log().debug(
                        "[HIVE] turn failure hook failed: %s", e
                    )
            for attr in ("turn", "_current_turn"):
                obj = getattr(self, attr, None)
                if obj is None:
                    continue
                try:
                    if callable(getattr(obj, "mark_failed", None)):
                        obj.mark_failed(reason)
                    if hasattr(obj, "status"):
                        setattr(obj, "status", "failed")
                    if hasattr(obj, "error"):
                        setattr(obj, "error", reason)
                except Exception:
                    pass
            return True
        except Exception as e:
            self._hive_log().warning(f"[HIVE] failed to mark turn failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────
    # MANAGED WORKERS (V5 #14: OpenHands delegate/suspend-resume + MetaGPT
    # cause_by-typed routing). All bookkeeping is defensive and never raises.
    # ─────────────────────────────────────────────────────────────────────

    def _hive_relations(self) -> Dict[str, Dict[str, str]]:
        """Return the lazy parent/child + cause_by relation dicts.

        Shape: ``{"parent": {child_id: parent_turn_id},
        "cause_by": {child_id: cause_by}}``. Never raises.
        """
        relations = getattr(self, "_hive_relations_store", None)
        if relations is None:
            relations = {"parent": {}, "cause_by": {}}
            self._hive_relations_store = relations
        return relations

    def _hive_states(self) -> Dict[str, str]:
        """Return the lazy worker lifecycle state dict (``worker_id -> state``)."""
        states = getattr(self, "_hive_states_store", None)
        if states is None:
            states = {}
            self._hive_states_store = states
        return states

    def _hive_state(self, worker_id: str) -> str:
        """Return a worker's state ("running"/"suspended"/"done"); "" when unknown."""
        try:
            return str(self._hive_states().get(worker_id, "") or "")
        except Exception:
            return ""

    async def _hive_spawn_managed(
        self, task: str, *, parent_turn_id: str = "", cause_by: str = ""
    ) -> Dict[str, Any]:
        """Spawn a tracked hive worker, recording parent/cause_by relations (#14).

        Delegates to the existing spawn path (``_maybe_spawn_hive``) and
        records parent/child + ``cause_by`` refs keyed by the generated worker
        id so a result can be routed back mid-plan (OpenHands delegate +
        MetaGPT cause_by style). Returns a dict carrying ``worker_id``,
        ``result`` (whatever the spawn path returned), ``parent_turn_id`` and
        ``cause_by``. Never raises.
        """
        try:
            worker_id = f"hive_{uuid.uuid4().hex[:12]}"
            relations = self._hive_relations()
            if parent_turn_id:
                relations["parent"][worker_id] = str(parent_turn_id)
            if cause_by:
                relations["cause_by"][worker_id] = str(cause_by)
            spawn = getattr(self, "_maybe_spawn_hive", None)
            result = None
            if callable(spawn):
                try:
                    result = await spawn(task)
                except Exception as e:
                    self._hive_update_subagent_state(
                        worker_id,
                        status="failed",
                        role="managed",
                        parent=str(parent_turn_id or ""),
                        reason=str(e)[:200],
                        started_at=time.time(),
                    )
                    self._hive_log().warning(
                        f"[HIVE] managed spawn failed (ignored): {e}"
                    )
            self._hive_update_subagent_state(
                worker_id,
                status="succeeded" if result else "spawned",
                role="managed",
                parent=str(parent_turn_id or ""),
                started_at=time.time(),
            )
            return {
                "worker_id": worker_id,
                "result": result,
                "parent_turn_id": relations["parent"].get(worker_id, ""),
                "cause_by": relations["cause_by"].get(worker_id, ""),
            }
        except Exception as e:
            self._hive_log().warning(f"[HIVE] managed spawn error (ignored): {e}")
            return {"worker_id": "", "result": None, "parent_turn_id": "", "cause_by": ""}

    async def _hive_suspend(self, worker_id: str) -> bool:
        """Suspend a worker in "running"/"" state; False otherwise. Never raises."""
        try:
            states = self._hive_states()
            if states.get(worker_id, "") not in ("running", ""):
                return False
            states[worker_id] = "suspended"
            await self._emit_hive_stage("suspend", worker_id)
            return True
        except Exception:
            return False

    async def _hive_resume(self, worker_id: str) -> bool:
        """Resume a "suspended" worker to "running"; False otherwise. Never raises."""
        try:
            states = self._hive_states()
            if states.get(worker_id, "") != "suspended":
                return False
            states[worker_id] = "running"
            await self._emit_hive_stage("resume", worker_id)
            return True
        except Exception:
            return False

    async def _emit_hive_stage(self, action: str, worker_id: str) -> None:
        """Emit a ``hive`` stage event for suspend/resume; guarded, never raises."""
        try:
            emitter = getattr(self, "_emit_stage_event", None)
            if not callable(emitter):
                return
            result = emitter("hive", action, worker_id, status="done")
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    async def _hive_route_result(self, worker_id: str, result: dict) -> str:
        """Return the recorded ``cause_by`` target for a worker result; "" when none.

        When a ``cause_by`` is recorded, emits a ``subagent.routed`` runtime
        event carrying the worker id, cause_by target and a result preview
        (MetaGPT cause_by-typed routing). Never raises.
        """
        try:
            cause_by = self._hive_relations()["cause_by"].get(worker_id, "") or ""
            if not cause_by:
                return ""
            emitter = getattr(self, "_emit_runtime_event", None)
            if callable(emitter):
                raw = result if isinstance(result, dict) else {}
                preview = str(raw.get("result") or raw.get("output") or result or "")[:200]
                await emitter(
                    "subagent.routed",
                    "Sub-agent result routed",
                    "done",
                    event_id=f"hive_route_{worker_id}",
                    payload={
                        "worker_id": worker_id,
                        "cause_by": cause_by,
                        "result_preview": preview,
                    },
                )
            return cause_by
        except Exception:
            return ""
