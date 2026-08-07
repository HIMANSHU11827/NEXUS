"""V5Control — V5 run control mixin for the V5 loop.

Provides the V5 loop with the same run-control surface the V1 loop has:

- ``abort()`` / ``_abort_requested()`` / ``_check_abort()`` — cooperative
  abort signalling backed by ``self._abort_flag`` (an ``asyncio.Event`` owned
  by the core ``NexusLoopV5``; the core clears it at the start of every turn,
  this mixin only sets and checks it).  V1 origin:
  ``orchestrators/loop.py`` line 4148 ``def abort(): self._abort_flag.set()``.
- ``_fire_post_tool_hooks()`` — fires ``post_tool_call`` lifecycle hooks after
  a tool execution, mirroring the V1 loop: ``loop.py`` lines 1100-1101
  (``self.hooks.trigger("post_tool_call", tool_calls, observations)`` plus
  ``self.kernel.plugins.trigger_hooks(...)``).
- ``_register_phase_hook()`` / ``_fire_phase_hooks()`` — Claude Code /
  OpenClaw-style phase hooks with matchers: hooks registered per
  ``(position, phase)`` fire on ``pre_phase`` / ``post_phase`` state
  transitions and may block via the JSON stdout contract (a dict with a
  ``"decision"`` key, a plain ``"block"`` string, or a JSON string wrapping
  either).
- ``_init_budget()`` / ``_budget_tick()`` / ``_budget_exceeded()`` /
  ``_budget_report()`` — per-run budget and cost telemetry
  (``max_turns`` / ``max_budget_usd`` from ``runtime.budget`` or the
  ``NEXUS_MAX_TURNS`` / ``NEXUS_MAX_BUDGET_USD`` env vars).
- ``_snapshot_workspace()`` / ``_rollback_snapshot()`` / ``_undo_last()`` —
  per-turn git-based workspace snapshots under
  ``<root_dir>/.nexus_v5/snapshots/<turn_id>/`` with restore-by-copy and
  ``git apply`` patch fallback.

Safe to mix into any class exposing ``runtime.hooks``, ``kernel``,
``logger``, ``session_id``, ``root_dir`` and (when present) ``_abort_flag``;
every attribute access is guarded and this module never raises.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


class V5Control:
    """Run control mixin: abort + phase hooks + budget + workspace snapshots."""

    # ─────────────────────────────────────────────────────────────────────
    # ABORT (V5: orchestrators/loop.py:4148)
    # ─────────────────────────────────────────────────────────────────────

    def abort(self, turn_id: str = "", reason: str = "user_cancelled") -> None:
        """Signal the loop to stop after the current turn.

        Idempotent — setting the flag twice is a no-op.  The core
        ``NexusLoopV5`` owns the flag and clears it at the start of every
        turn; this method only ever sets it (or creates one if the core
        class did not yet initialize it).
        """
        registry = getattr(self, "_run_controls", None)
        target = str(turn_id or getattr(self, "_current_turn_id", "") or "")
        if registry is not None and target:
            registry.request_cancel(target, reason)
            self.logger.info("[ABORT] abort requested for run %s", target)
            return
        flag = getattr(self, "_abort_flag", None)
        if flag is None:
            flag = asyncio.Event()
            self._abort_flag = flag
        flag.set()
        self.logger.info("[ABORT] abort requested for session %s", self.session_id)

    def _abort_requested(self) -> bool:
        """True when an abort has been requested (defaults to False)."""
        registry = getattr(self, "_run_controls", None)
        current = str(getattr(self, "_current_turn_id", "") or "")
        if registry is not None and current:
            control = registry.get(current)
            if control is not None:
                return control.cancelled
        flag = getattr(self, "_abort_flag", None)
        if flag is None:
            return False
        return bool(flag.is_set())

    def _check_abort(self) -> None:
        """Raise CancelledError when an abort was requested.

        The core's ``_turn_events`` already handles ``CancelledError`` and
        yields a failed done event, so raising is safe and correct.  The
        core calls this between phases.
        """
        if self._abort_requested():
            raise asyncio.CancelledError("V5 loop abort requested")

    def _check_deadline(self) -> None:
        """Raise a timeout when the current run's monotonic budget expires."""
        registry = getattr(self, "_run_controls", None)
        current = str(getattr(self, "_current_turn_id", "") or "")
        control = registry.get(current) if registry is not None and current else None
        if control is not None and control.timed_out:
            raise asyncio.TimeoutError("V5 run deadline exceeded")

    # ─────────────────────────────────────────────────────────────────────
    # POST_TOOL_CALL HOOKS (V5: orchestrators/loop.py:1100-1101)
    # ─────────────────────────────────────────────────────────────────────

    async def _fire_post_tool_hooks(
        self, call: Any, status: str, result: str = "", error: str = ""
    ) -> None:
        """Fire post_tool_call lifecycle hooks after one tool execution.

        Mirrors the V1 loop: the runtime ``HookRegistry`` is notified first,
        then the kernel plugin hook system.  Both are wrapped in try/except
        and every attribute access is guarded — a failure here never breaks
        the loop.
        """
        tool_calls = [call]
        observations = [f"[{status}] {result or error}"[:1000]]

        # Runtime HookRegistry (async trigger — core.HookRegistry)
        hooks = getattr(getattr(self, "runtime", None), "hooks", None)
        trigger = getattr(hooks, "trigger", None)
        if callable(trigger):
            try:
                await trigger("post_tool_call", tool_calls, observations)
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"post_tool_call hooks failed: {e}")

        # Kernel plugin hooks
        kernel = getattr(self, "kernel", None)
        plugins = getattr(kernel, "plugins", None)
        trigger_hooks = getattr(plugins, "trigger_hooks", None)
        if callable(trigger_hooks):
            try:
                await trigger_hooks("post_tool_call", tool_calls, observations)
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"plugin post_tool_call hooks failed: {e}")

        # Evolution gap detection (deterministic — V5)
        gap_fn = getattr(self, "_handle_evolution_gaps", None)
        if callable(gap_fn):
            try:
                gap_fn(tool_calls, observations)
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"evolution gap detection failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # PHASE HOOKS (Claude Code / OpenClaw matcher contract)
    # ─────────────────────────────────────────────────────────────────────

    def _register_phase_hook(self, position: str, phase: str, hook: Callable) -> bool:
        """Register a hook for a (position, phase) transition.

        Args:
            position: ``"pre_phase"`` or ``"post_phase"``.
            phase: The V5 phase/state name (e.g. ``"acting"``).
            hook: Sync or async callable. May return a dict with
                ``{"decision": "block"/"allow", "reason": str}``, a plain
                ``"block"``/``"allow"`` string, or a JSON string wrapping
                either (JSON stdout contract).

        Returns:
            True when registered. Hooks are deduplicated by identity.
        """
        try:
            if position not in ("pre_phase", "post_phase"):
                return False
            if not phase or not callable(hook):
                return False
            registry = getattr(self, "_phase_hooks", None)
            if registry is None:
                registry = {}
                self._phase_hooks = registry
            key = (position, str(phase))
            hooks = registry.setdefault(key, [])
            if hook not in hooks:
                hooks.append(hook)
            return True
        except Exception:
            return False

    async def _fire_phase_hooks(self, position: str, phase: str) -> str:
        """Fire hooks registered for (position, phase); blocks on first block.

        Args:
            position: ``"pre_phase"`` or ``"post_phase"``.
            phase: The V5 phase/state name.

        Returns:
            "" when allowed, or the blocking hook's reason string. Guarded —
            a failing hook is logged and skipped, never raised.
        """
        try:
            registry = getattr(self, "_phase_hooks", None)
            if not registry:
                return ""
            hooks = registry.get((str(position), str(phase)))
            if not hooks:
                return ""
            for hook in list(hooks):
                try:
                    if asyncio.iscoroutinefunction(hook):
                        result = await self._invoke_phase_hook(hook, position, phase)
                    else:
                        result = await asyncio.to_thread(
                            self._invoke_phase_hook, hook, position, phase
                        )
                except Exception as e:  # noqa: BLE001
                    self.logger.warning(
                        f"phase hook ({position}/{phase}) failed: {e}"
                    )
                    continue
                reason = self._parse_hook_decision(result)
                if reason:
                    self.logger.warning(
                        f"phase hook ({position}/{phase}) blocked: {reason}"
                    )
                    return reason
            return ""
        except Exception:
            return ""

    @staticmethod
    def _invoke_phase_hook(hook: Callable, position: str, phase: str) -> Any:
        """Invoke a hook, adapting to its signature (kwargs-first, guarded)."""
        try:
            params = inspect.signature(hook).parameters
            has_var_keyword = any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if has_var_keyword or ("position" in params and "phase" in params):
                return hook(position=position, phase=phase)
            if "phase" in params:
                return hook(phase=phase)
            positional = [
                p
                for p in params.values()
                if p.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if len(positional) >= 2:
                return hook(position, phase)
            if len(positional) == 1:
                return hook(phase)
            return hook()
        except (TypeError, ValueError):
            return hook()

    @staticmethod
    def _parse_hook_decision(result: Any) -> str:
        """Extract a block reason from a hook result ("" when allowed).

        Supports the JSON stdout contract: a dict with a ``"decision"`` key,
        a plain ``"block"`` string, or a JSON string wrapping either.
        """
        try:
            payload = result
            if isinstance(payload, str):
                stripped = payload.strip()
                if stripped.lower() == "block":
                    return "blocked by phase hook"
                try:
                    payload = json.loads(stripped)
                except (ValueError, TypeError):
                    return ""
            if isinstance(payload, dict):
                decision = str(payload.get("decision") or "").strip().lower()
                if decision == "block":
                    return str(payload.get("reason") or "blocked by phase hook")
            return ""
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────────────
    # PER-RUN BUDGET + COST TELEMETRY (Codex lesson)
    # ─────────────────────────────────────────────────────────────────────

    def _init_budget(self) -> None:
        """Lazily initialize the per-run budget tracking dict.

        Reads ``runtime.budget`` (a dict) and the ``NEXUS_MAX_TURNS`` /
        ``NEXUS_MAX_BUDGET_USD`` env vars; defaults are 50 turns and
        unlimited cost (``max_budget_usd = 0``).
        """
        try:
            if getattr(self, "_budget", None) is not None:
                return
            max_turns = 50
            max_budget_usd = 0.0
            budget = getattr(getattr(self, "runtime", None), "budget", None)
            if isinstance(budget, dict):
                try:
                    max_turns = int(budget.get("max_turns", max_turns) or max_turns)
                except (TypeError, ValueError):
                    pass
                try:
                    max_budget_usd = float(
                        budget.get("max_budget_usd", max_budget_usd) or 0.0
                    )
                except (TypeError, ValueError):
                    pass
            env_turns = os.environ.get("NEXUS_MAX_TURNS")
            if env_turns:
                try:
                    max_turns = int(env_turns)
                except ValueError:
                    pass
            env_budget = os.environ.get("NEXUS_MAX_BUDGET_USD")
            if env_budget:
                try:
                    max_budget_usd = float(env_budget)
                except ValueError:
                    pass
            self._budget = {
                "max_turns": max(0, int(max_turns)),
                "max_budget_usd": max(0.0, float(max_budget_usd)),
                "turns": 0,
                "cost": 0.0,
                "tokens": 0,
                "started": time.time(),
            }
        except Exception:
            self._budget = {
                "max_turns": 50,
                "max_budget_usd": 0.0,
                "turns": 0,
                "cost": 0.0,
                "tokens": 0,
                "started": time.time(),
            }

    def _budget_tick(self, tokens: int = 0, cost: float = 0.0) -> Dict[str, Any]:
        """Record one executed turn with token/cost telemetry.

        Returns a copy of the budget dict after the tick. Never raises.
        """
        try:
            budget = getattr(self, "_budget", None)
            if budget is None:
                self._init_budget()
                budget = self._budget
            budget["turns"] = int(budget.get("turns", 0)) + 1
            budget["tokens"] = int(budget.get("tokens", 0)) + max(0, int(tokens))
            budget["cost"] = float(budget.get("cost", 0.0)) + max(0.0, float(cost))
            return dict(budget)
        except Exception:
            return {"turns": 0, "tokens": 0, "cost": 0.0}

    def _budget_exceeded(self) -> bool:
        """True when the run exceeded its turn or cost budget. Never raises."""
        try:
            budget = getattr(self, "_budget", None)
            if budget is None:
                self._init_budget()
                budget = self._budget
            max_budget = float(budget.get("max_budget_usd", 0.0) or 0.0)
            if max_budget > 0.0 and float(budget.get("cost", 0.0)) >= max_budget:
                return True
            max_turns = int(budget.get("max_turns", 0) or 0)
            if max_turns > 0 and int(budget.get("turns", 0)) >= max_turns:
                return True
            return False
        except Exception:
            return False

    def _budget_report(self) -> Dict[str, Any]:
        """Snapshot budget/cost telemetry for the ``done`` event payload."""
        try:
            budget = getattr(self, "_budget", None)
            if budget is None:
                self._init_budget()
                budget = self._budget
            started = float(budget.get("started", time.time()) or time.time())
            return {
                "turns": int(budget.get("turns", 0)),
                "tokens": int(budget.get("tokens", 0)),
                "cost_usd": round(float(budget.get("cost", 0.0)), 6),
                "duration_s": round(max(0.0, time.time() - started), 3),
                "max_turns": int(budget.get("max_turns", 0)),
                "max_budget_usd": round(float(budget.get("max_budget_usd", 0.0)), 6),
            }
        except Exception:
            return {
                "turns": 0,
                "tokens": 0,
                "cost_usd": 0.0,
                "duration_s": 0.0,
                "max_turns": 0,
                "max_budget_usd": 0.0,
            }

    # ─────────────────────────────────────────────────────────────────────
    # WORKSPACE ROLLBACK / GIT SNAPSHOT (Codex lesson)
    # ─────────────────────────────────────────────────────────────────────

    _SNAPSHOT_ROOT = ".nexus_v5"
    _SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024

    def _snapshot_workspace(self, turn_id: str = "") -> str:
        """Capture a per-turn git snapshot of modified tracked files.

        Modified files (``git diff --name-only``) are saved under
        ``<root_dir>/.nexus_v5/snapshots/<turn_id>/`` preserving relative
        paths; each file stores the committed (``HEAD``) content so a later
        rollback restores the pre-turn state. When nothing is modified a
        ``snapshot.patch`` (``git diff --binary``) is written instead.
        Files larger than 2MB are skipped.

        Returns:
            The snapshot directory path, or "" on any failure (no git repo,
            git missing, subprocess error).
        """
        try:
            root = os.path.abspath(
                str(getattr(self, "root_dir", "") or os.getcwd())
            )
            safe_turn = re.sub(r"[^A-Za-z0-9_.-]", "_", str(turn_id or ""))
            if not safe_turn:
                safe_turn = getattr(self, "_current_turn_id", "") or ""
                safe_turn = re.sub(r"[^A-Za-z0-9_.-]", "_", safe_turn)
            if not safe_turn:
                safe_turn = f"turn_{int(time.time() * 1000)}"
            snap_dir = os.path.join(
                root, self._SNAPSHOT_ROOT, "snapshots", safe_turn
            )
            repo = subprocess.run(
                ["git", "-C", root, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=30,
            )
            if repo.returncode != 0 or os.path.normcase(os.path.abspath(repo.stdout.strip())) != os.path.normcase(root):
                self.logger.info(
                    "Workspace snapshot skipped: root is not a repository root at %s",
                    root,
                )
                return ""

            proc = subprocess.run(
                ["git", "-C", root, "diff", "--name-only"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                self.logger.info(
                    "Workspace snapshot skipped: not a git repo at %s", root
                )
                return ""

            os.makedirs(snap_dir, exist_ok=True)

            names = [name for name in proc.stdout.splitlines() if name.strip()]
            if not names:
                patch = subprocess.run(
                    ["git", "-C", root, "diff", "--binary"],
                    capture_output=True, timeout=30,
                )
                if patch.returncode == 0:
                    with open(os.path.join(snap_dir, "snapshot.patch"), "wb") as fh:
                        fh.write(patch.stdout)
                return snap_dir

            for name in names:
                src = os.path.join(root, name)
                if not os.path.isfile(src):
                    continue
                try:
                    if os.path.getsize(src) > self._SNAPSHOT_MAX_BYTES:
                        continue
                except OSError:
                    continue
                dst = os.path.join(snap_dir, name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                show = subprocess.run(
                    ["git", "-C", root, "show", f"HEAD:{name}"],
                    capture_output=True, timeout=30,
                )
                if show.returncode == 0:
                    if len(show.stdout) > self._SNAPSHOT_MAX_BYTES:
                        continue
                    with open(dst, "wb") as fh:
                        fh.write(show.stdout)
                else:
                    shutil.copy2(src, dst)
            return snap_dir
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Workspace snapshot failed: %s", e)
            return ""

    def _rollback_snapshot(self, turn_id: str) -> bool:
        """Restore the workspace from a previously taken snapshot.

        Walks the snapshot dir and copies every captured file back over the
        workspace file (creating parent dirs); when a ``snapshot.patch`` is
        present instead, applies it via ``git apply``.

        Returns:
            True when at least one file was restored (or the patch applied /
            was a no-op). Never raises.
        """
        try:
            root = os.path.abspath(
                str(getattr(self, "root_dir", "") or os.getcwd())
            )
            safe_turn = re.sub(r"[^A-Za-z0-9_.-]", "_", str(turn_id or ""))
            snap_dir = os.path.join(
                root, self._SNAPSHOT_ROOT, "snapshots", safe_turn
            )
            if not os.path.isdir(snap_dir):
                self.logger.info("No snapshot found for turn '%s'", turn_id)
                return False

            patch_path = os.path.join(snap_dir, "snapshot.patch")
            if os.path.isfile(patch_path):
                if os.path.getsize(patch_path) == 0:
                    return True
                proc = subprocess.run(
                    ["git", "-C", root, "apply", patch_path],
                    capture_output=True, text=True, timeout=30,
                )
                if proc.returncode != 0:
                    self.logger.warning(
                        "Snapshot patch apply failed: %s", proc.stderr.strip()
                    )
                    return False
                return True

            restored = False
            for dirpath, _dirnames, filenames in os.walk(snap_dir):
                for filename in filenames:
                    if filename == "snapshot.patch":
                        continue
                    src = os.path.join(dirpath, filename)
                    rel = os.path.relpath(src, snap_dir)
                    if rel.startswith(".."):
                        continue
                    dst = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    restored = True
            if not restored:
                self.logger.info(
                    "Snapshot for turn '%s' contained no restorable files",
                    turn_id,
                )
            return restored
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Workspace rollback failed: %s", e)
            return False

    def _undo_last(self) -> bool:
        """Roll back the most recent snapshot (max mtime). Never raises."""
        try:
            root = os.path.abspath(
                str(getattr(self, "root_dir", "") or os.getcwd())
            )
            snap_root = os.path.join(root, self._SNAPSHOT_ROOT, "snapshots")
            if not os.path.isdir(snap_root):
                return False
            snap_dirs = [
                os.path.join(snap_root, entry)
                for entry in os.listdir(snap_root)
                if os.path.isdir(os.path.join(snap_root, entry))
            ]
            if not snap_dirs:
                return False
            latest = max(snap_dirs, key=os.path.getmtime)
            return self._rollback_snapshot(os.path.basename(latest))
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Undo last failed: %s", e)
            return False
